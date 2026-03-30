"""A365 data processing helpers."""

import asyncio
import importlib
import os

from Core.get_recommendation import get_recommendation
from Core.spinner import _stdout_lock, get_timestamp


async def get_a365_info(a365_client, progress_callback=None):
    """Process A365 package catalog payload into orchestrator output format."""
    if not isinstance(a365_client, dict):
        return {
            'available': False,
            'reason': 'A365 catalog payload is unavailable',
            'recommendations': []
        }

    packages = a365_client.get('value', [])
    if not isinstance(packages, list):
        packages = []

    # Show a single status line so users know which summarization mode is active.
    try:
        summarize_module = importlib.import_module("Core.a365.copilot_summarizer")
        get_runtime_mode = getattr(summarize_module, "get_runtime_mode")
        mode = get_runtime_mode()
        with _stdout_lock:
            if mode.get("enabled"):
                print(
                    f"\n[{get_timestamp()}] [INFO] A365 observation summarization: GitHub Copilot enabled "
                    f"(token source: {mode.get('source')}, model: {mode.get('model')})."
                )
            else:
                print(f"\n[{get_timestamp()}] [INFO] A365 observation summarization: using fallback summaries ({mode.get('reason')}).")
    except Exception:
        mode = {"enabled": False}
        with _stdout_lock:
            print(f"\n[{get_timestamp()}] [INFO] A365 observation summarization: using fallback summaries.")

    # Prefer chunked bulk summarization to avoid one API call per row.
    summary_delay_seconds = 0.0
    precomputed_summaries = {}
    bulk_attempted = False
    bulk_success_ratio = 0.0
    per_row_retry_limit = 0
    per_row_retries_used = 0
    if mode.get("enabled"):
        with _stdout_lock:
            print(f"[{get_timestamp()}] [INFO] A365 Copilot summarization running in bulk mode when possible.")

    async def build_recommendation(package):
        if not isinstance(package, dict):
            return []

        feature_name = "CATALOG_PACKAGE"
        sku_name = package.get('displayName') or package.get('name') or package.get('id') or 'A365 Package'
        status = package.get('status') or 'Success'

        rec = await asyncio.to_thread(
            get_recommendation,
            'a365',
            feature_name,
            sku_name,
            status,
            None,
            package
        )

        if isinstance(rec, list):
            return rec
        return [rec]

    valid_packages = [package for package in packages if isinstance(package, dict)]
    total_valid = len(valid_packages)

    # Start processing bar immediately after gathering, including bulk summarization time.
    if progress_callback:
        progress_callback(0, total_valid)

    if mode.get("enabled") and total_valid > 0:
        try:
            summarize_module = importlib.import_module("Core.a365.copilot_summarizer")
            summarize_package_rows_bulk = getattr(summarize_module, "summarize_package_rows_bulk")
            bulk_attempted = True
            try:
                bulk_chunk_size = int(os.getenv("A365_SUMMARY_BULK_CHUNK_SIZE", "25") or "25")
            except Exception:
                bulk_chunk_size = 25
            bulk_chunk_size = max(5, min(100, bulk_chunk_size))

            with _stdout_lock:
                print(
                    f"[{get_timestamp()}] [INFO] A365 bulk summarization configured: {total_valid} rows, chunk size {bulk_chunk_size}."
                )

            def bulk_progress_callback(done_chunks, total_chunks):
                if total_chunks <= 0:
                    return
                pct = int((done_chunks / total_chunks) * 100)
                if progress_callback and total_valid > 0:
                    # Reflect bulk completion in the same processing bar.
                    approx_processed = min(total_valid, done_chunks * bulk_chunk_size)
                    progress_callback(approx_processed, total_valid)
                with _stdout_lock:
                    print(
                        f"[{get_timestamp()}] [INFO] A365 bulk summarization progress: {done_chunks}/{total_chunks} chunks ({pct}%)."
                    )

            precomputed_summaries = await asyncio.to_thread(
                summarize_package_rows_bulk,
                valid_packages,
                bulk_chunk_size,
                bulk_progress_callback,
            )

            with _stdout_lock:
                print(
                    f"[{get_timestamp()}] [INFO] A365 bulk summarization complete: {len(precomputed_summaries)}/{total_valid} rows summarized via Copilot."
                )

            bulk_success_ratio = (len(precomputed_summaries) / total_valid) if total_valid > 0 else 0.0
            if bulk_success_ratio < 0.5:
                try:
                    per_row_retry_limit = int(os.getenv("A365_PER_ROW_SUMMARY_LIMIT", "40") or "40")
                except Exception:
                    per_row_retry_limit = 40
                per_row_retry_limit = max(0, min(200, per_row_retry_limit))
                if per_row_retry_limit > 0:
                    with _stdout_lock:
                        print(
                            f"[{get_timestamp()}] [INFO] A365 bulk coverage is low ({bulk_success_ratio:.0%}); enabling per-row Copilot retries for up to {per_row_retry_limit} rows."
                        )
        except Exception as ex:
            with _stdout_lock:
                print(
                    f"[{get_timestamp()}] [WARN] A365 bulk summarization unavailable ({type(ex).__name__}); falling back to per-row summarization."
                )
            precomputed_summaries = {}

    recommendations = []
    for idx, package in enumerate(valid_packages, start=1):
        package_payload = dict(package)
        bulk_summary = precomputed_summaries.get(idx - 1)
        if isinstance(bulk_summary, str) and bulk_summary.strip():
            package_payload["_precomputed_summary"] = bulk_summary.strip()
            package_payload["_skip_row_summarization"] = True
        elif bulk_attempted:
            allow_retry = bulk_success_ratio < 0.5 and per_row_retries_used < per_row_retry_limit
            if allow_retry:
                per_row_retries_used += 1
                package_payload["_skip_row_summarization"] = False
            else:
                package_payload["_skip_row_summarization"] = True

        result = await build_recommendation(package_payload)
        recommendations.extend(result)
        if progress_callback:
            progress_callback(idx, total_valid)
        if summary_delay_seconds > 0:
            await asyncio.sleep(summary_delay_seconds)

    return {
        'available': True,
        'has_a365': True,
        'total_packages': len(packages),
        'packages': packages,
        'recommendations': recommendations
    }
