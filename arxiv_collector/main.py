"""
ArXiv Research Collector Main Entry Point.
Executes automated discovery, deduplication, and downloading of quantitative finance research papers.
Supports interactive prompt, CLI arguments (--test, --full), and robust error handling.
"""
from datetime import datetime
from pathlib import Path
import argparse
import logging
import sys
import time

# Ensure imports work seamlessly regardless of whether run from root or inside arxiv_collector/
_PKG_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _PKG_DIR.parent
for _p in (str(_PKG_DIR), str(_ROOT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from arxiv_collector.config import (
        KEYWORDS_FILE,
        RESULTS_PER_KEYWORD,
        TEST_RESULTS,
        DATABASE_PATH,
        PDF_DIRECTORY,
        load_keywords,
    )
    from arxiv_collector.database import Database
    from arxiv_collector.arxiv_client import ArXivClient
    from arxiv_collector.downloader import PDFDownloader
    from arxiv_collector.utils import setup_logger, is_valid_pdf
except ImportError:
    from config import (
        KEYWORDS_FILE,
        RESULTS_PER_KEYWORD,
        TEST_RESULTS,
        DATABASE_PATH,
        PDF_DIRECTORY,
        load_keywords,
    )
    from database import Database
    from arxiv_client import ArXivClient
    from downloader import PDFDownloader
    from utils import setup_logger, is_valid_pdf


def run_test_mode(
    client: ArXivClient,
    db: Database,
    downloader: PDFDownloader,
    keywords: list[str],
    logger: logging.Logger,
    max_results: int = TEST_RESULTS
) -> None:
    """Execute TEST mode on the first keyword with max 5 results."""
    if not keywords:
        print("ERROR: No keywords available for TEST mode.")
        return

    test_keyword = keywords[0]

    print("\nTEST MODE\n")
    print("Keyword:")
    print(f"{test_keyword}\n")
    print(f"Fetching top {max_results} papers...\n")

    logger.info(f"--- STARTING TEST MODE on keyword '{test_keyword}' (max {max_results}) ---")

    try:
        papers = client.search(keyword=test_keyword, max_results=max_results)
    except Exception as exc:
        print(f"API Error fetching papers for '{test_keyword}': {exc}")
        logger.error(f"TEST mode API search failed: {exc}")
        return

    downloaded_count = 0
    skipped_count = 0
    failed_count = 0

    for idx, paper in enumerate(papers, start=1):
        arxiv_id = paper["arxiv_id"]
        title_snippet = (paper["title"][:55] + "...") if len(paper["title"]) > 55 else paper["title"]

        # 1. Record paper discovery & rank in SQLite
        is_new, record = db.upsert_paper_discovery(paper, keyword=test_keyword, rank=idx)

        # 2. Check if file is already on disk and valid
        target_path = downloader.get_target_path(arxiv_id)
        already_on_disk = is_valid_pdf(target_path)

        # Check if database says it's downloaded, but file is missing
        needs_redownload = (not already_on_disk) and (record.get("download_status") == "downloaded")

        if already_on_disk and not needs_redownload:
            print(f"[{idx}/{len(papers)}] {arxiv_id} - {title_snippet} (SKIP: already downloaded)")
            db.update_download_status(arxiv_id, "downloaded", str(target_path))
            skipped_count += 1
            logger.info(f"TEST [{idx}/{len(papers)}] SKIP {arxiv_id} (already downloaded)")
        else:
            action_desc = "REDOWNLOAD" if needs_redownload else "DOWNLOAD"
            print(f"[{idx}/{len(papers)}] {arxiv_id} - {title_snippet} ({action_desc})...", end="", flush=True)

            res = downloader.download_paper(paper, force_redownload=needs_redownload)
            if res.success:
                print(f" [OK] -> {res.file_path.name}")
                db.update_download_status(arxiv_id, "downloaded", str(res.file_path))
                downloaded_count += 1
                logger.info(f"TEST [{idx}/{len(papers)}] OK {arxiv_id}")
            else:
                print(f" [FAILED: {res.message}]")
                db.update_download_status(arxiv_id, "failed")
                failed_count += 1
                logger.warning(f"TEST [{idx}/{len(papers)}] FAILED {arxiv_id}: {res.message}")

    print("\n" + "-" * 30)
    print(f"Downloaded: {downloaded_count}")
    print(f"Skipped:    {skipped_count}")
    print(f"Failed:     {failed_count}")
    print("-" * 30 + "\n")

    logger.info(
        f"TEST mode complete. Downloaded: {downloaded_count}, Skipped: {skipped_count}, Failed: {failed_count}"
    )


def run_full_mode(
    client: ArXivClient,
    db: Database,
    downloader: PDFDownloader,
    keywords: list[str],
    logger: logging.Logger,
    results_per_keyword: int = RESULTS_PER_KEYWORD
) -> None:
    """Execute FULL mode over all keywords."""
    total_keywords = len(keywords)

    print("\nStarting FULL MODE...\n")
    logger.info(f"--- STARTING FULL MODE ({total_keywords} keywords, {results_per_keyword} results/kw) ---")

    # Global tracking counters for summary
    total_papers_discovered = 0
    total_new_papers = 0
    total_already_known = 0
    total_downloaded = 0
    total_skipped = 0
    total_failed = 0

    start_time = time.time()

    for kw_idx, keyword in enumerate(keywords, start=1):
        print(f"[{kw_idx:03d}/{total_keywords:03d}] {keyword}")
        logger.info(f"Processing [{kw_idx}/{total_keywords}] keyword='{keyword}'")

        try:
            papers = client.search(
                keyword=keyword,
                max_results=results_per_keyword
            )
        except Exception as exc:
            print(f"    API ERROR: {exc} (continuing to next keyword)")
            logger.error(f"Keyword search failed for '{keyword}': {exc}")
            continue

        kw_found = len(papers)
        kw_new = 0
        kw_skipped = 0
        kw_downloaded = 0
        kw_failed = 0

        for rank, paper in enumerate(papers, start=1):
            total_papers_discovered += 1
            arxiv_id = paper["arxiv_id"]

            # Database upsert & rank tracking
            is_new, record = db.upsert_paper_discovery(paper, keyword=keyword, rank=rank)
            if is_new:
                kw_new += 1
                total_new_papers += 1
            else:
                total_already_known += 1

            # Check if PDF already physically exists
            target_path = downloader.get_target_path(arxiv_id)
            already_on_disk = is_valid_pdf(target_path)
            needs_redownload = (not already_on_disk) and (record.get("download_status") == "downloaded")

            if already_on_disk and not needs_redownload:
                kw_skipped += 1
                total_skipped += 1
                # Ensure status in DB reflects current state
                db.update_download_status(arxiv_id, "downloaded", str(target_path))
                logger.debug(f"Paper {arxiv_id} already exists on disk. Skipping download.")
            else:
                # Needs download (new or redownload of missing file)
                res = downloader.download_paper(paper, force_redownload=needs_redownload)
                if res.success:
                    db.update_download_status(arxiv_id, "downloaded", str(res.file_path))
                    kw_downloaded += 1
                    total_downloaded += 1
                else:
                    db.update_download_status(arxiv_id, "failed")
                    kw_failed += 1
                    total_failed += 1
                    logger.warning(f"Download failed for {arxiv_id}: {res.message}")

        print(f"    Found:   {kw_found}")
        print(f"    New:     {kw_new}")
        print(f"    Skipped: {kw_skipped}")
        print(f"    Failed:  {kw_failed}\n")

        logger.info(
            f"Keyword '{keyword}' summary: Found={kw_found}, New={kw_new}, "
            f"Skipped={kw_skipped}, Downloaded={kw_downloaded}, Failed={kw_failed}"
        )

    elapsed_s = time.time() - start_time
    minutes = int(elapsed_s // 60)
    seconds = int(elapsed_s % 60)

    print("========================================")
    print(" COMPLETE")
    print("========================================")
    print(f"Keywords processed: {total_keywords}")
    print(f"Papers discovered:  {total_papers_discovered}")
    print(f"New papers:         {total_new_papers}")
    print(f"Already known:      {total_already_known}")
    print(f"Downloaded:         {total_downloaded}")
    print(f"Failed:             {total_failed}")
    print(f"Time elapsed:       {minutes}m {seconds}s")
    print("========================================\n")

    logger.info(
        f"FULL run complete in {minutes}m {seconds}s. Keywords={total_keywords}, "
        f"Discovered={total_papers_discovered}, New={total_new_papers}, "
        f"AlreadyKnown={total_already_known}, Downloaded={total_downloaded}, Failed={total_failed}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ArXiv PDF Research Collector - Harvest Quantitative Finance Papers"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--test",
        action="store_true",
        help="Run immediately in TEST mode (1st keyword, top 5 results, real download)"
    )
    group.add_argument(
        "--full",
        action="store_true",
        help="Run immediately in FULL mode (all 100 keywords, 25 results/keyword)"
    )
    parser.add_argument(
        "--results-per-keyword",
        type=int,
        default=RESULTS_PER_KEYWORD,
        help=f"Number of results to fetch per keyword in FULL mode (default: {RESULTS_PER_KEYWORD})"
    )
    parser.add_argument(
        "--max-keywords",
        type=int,
        default=None,
        help="Optional limit on number of keywords to process in FULL mode"
    )

    args = parser.parse_args()

    # Initialize Logger
    logger = setup_logger()
    logger.info(f"Application starting at {datetime.now().isoformat()}")

    # Load Keywords
    try:
        keywords = load_keywords(KEYWORDS_FILE)
        if args.max_keywords and args.max_keywords > 0:
            keywords = keywords[:args.max_keywords]
    except Exception as exc:
        print(f"FATAL: Could not load keywords from {KEYWORDS_FILE}: {exc}")
        logger.critical(f"Failed to load keywords: {exc}")
        sys.exit(1)

    # Initialize Core Components
    db = Database(DATABASE_PATH)
    client = ArXivClient()
    downloader = PDFDownloader(pdf_dir=PDF_DIRECTORY)

    # Console Banner
    print("========================================")
    print(" ARXIV RESEARCH COLLECTOR")
    print("========================================")
    print(f"Keywords:          {len(keywords)}")
    print(f"Results / keyword: {args.results_per_keyword}")
    print("========================================")

    # Determine mode
    is_test = False
    if args.test:
        is_test = True
    elif args.full:
        is_test = False
    else:
        # Interactive prompt as specified in Requirement #5 and #23
        try:
            choice = input("\nRun in TEST mode? [y/N]: ").strip().lower()
            if choice in ("y", "yes"):
                is_test = True
            else:
                is_test = False
        except (EOFError, KeyboardInterrupt):
            print("\nAborted by user.")
            sys.exit(0)

    # Execute selected mode
    if is_test:
        run_test_mode(
            client=client,
            db=db,
            downloader=downloader,
            keywords=keywords,
            logger=logger,
            max_results=TEST_RESULTS
        )
    else:
        run_full_mode(
            client=client,
            db=db,
            downloader=downloader,
            keywords=keywords,
            logger=logger,
            results_per_keyword=args.results_per_keyword
        )


if __name__ == "__main__":
    main()
