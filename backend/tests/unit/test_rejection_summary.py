from app.domain.models import ImportCandidate, ImportInspection
from app.jobs.runner import _rejection_summary


def test_lists_each_file_with_its_reasons():
    inspection = ImportInspection(
        candidates=[
            ImportCandidate(
                relative_path="x",
                absolute_path="/downloads/completed/tv/Show.S01E01.mkv",
                rejection_reasons=["Not enough free space"],
            )
        ],
        all_rejected=True,
    )
    assert _rejection_summary(inspection, "/downloads/completed/tv") == (
        "All import candidates were rejected: Show.S01E01.mkv: Not enough free space"
    )


def test_no_candidates_names_the_path():
    inspection = ImportInspection(candidates=[], all_rejected=True)
    assert _rejection_summary(inspection, "/downloads/x") == (
        "Library found no importable files at /downloads/x"
    )
