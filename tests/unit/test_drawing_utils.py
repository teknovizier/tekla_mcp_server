"""
Unit tests for pure drawing helpers in `tekla.drawing_utils`.

These tests require a live Tekla Structures environment and will be skipped in CI environments
where Tekla is not available, since `drawing_utils` transitively imports `tekla/loader.py`.
"""

import logging
import os
from types import SimpleNamespace

import pytest

if os.getenv("CI") == "true":
    pytest.skip("Skipping all tests (Tekla not available in CI)", allow_module_level=True)

from tekla_mcp_server.tekla.drawing_utils import (
    compute_section_alignment,
    detect_section_parents,
)


class StubMark:
    def __init__(self, lp, rp):
        self.LeftPoint = SimpleNamespace(X=lp[0], Y=lp[1])
        self.RightPoint = SimpleNamespace(X=rp[0], Y=rp[1])


class StubView:
    def __init__(self, view_key, name, view_type, origin=(0.0, 0.0), scale=30.0, section_marks=()):
        self.view_key = view_key
        self.name = name
        self.view_type = view_type
        self.origin_x, self.origin_y = origin
        self.scale = scale
        self._section_marks = list(section_marks)

    def get_section_marks(self):
        return self._section_marks


class TestDetectSectionParents:
    def test_matches_section_view_to_mark_owner(self):
        mark = StubMark((872.0, 167.1), (4463.7, 167.1))
        parent = StubView("FrontView_1", "MAIN", "FrontView", section_marks=[("B", mark)])
        child = StubView("SectionView_2", "B", "SectionView")
        assert detect_section_parents([parent, child]) == {"SectionView_2": ("FrontView_1", mark)}

    def test_section_without_matching_mark_is_omitted(self):
        parent = StubView("FrontView_1", "MAIN", "FrontView", section_marks=[("A", StubMark((0, 0), (100, 0)))])
        child = StubView("SectionView_2", "B", "SectionView")
        assert detect_section_parents([parent, child]) == {}

    def test_non_section_views_are_omitted(self):
        parent = StubView("FrontView_1", "MAIN", "FrontView", section_marks=[("B", StubMark((0, 0), (100, 0)))])
        detail = StubView("DetailView_2", "B", "DetailView")
        assert detect_section_parents([parent, detail]) == {}

    def test_a_view_is_not_its_own_parent(self):
        # A section view that also carries a mark of its own name must not
        # match itself.
        view = StubView("SectionView_1", "B", "SectionView", section_marks=[("B", StubMark((0, 0), (100, 0)))])
        assert detect_section_parents([view]) == {}

    def test_duplicate_mark_name_warns_and_picks_first(self, caplog):
        # Two views holding a mark of the same name is ambiguous: the first by
        # insertion order wins, and a warning is logged so it is not silent.
        m1 = StubMark((0, 0), (100, 0))
        m2 = StubMark((0, 50), (100, 50))
        parent1 = StubView("FrontView_1", "MAIN", "FrontView", section_marks=[("B", m1)])
        parent2 = StubView("FrontView_3", "OTHER", "FrontView", section_marks=[("B", m2)])
        child = StubView("SectionView_2", "B", "SectionView")
        with caplog.at_level(logging.WARNING):
            result = detect_section_parents([parent1, parent2, child])
        assert result == {"SectionView_2": ("FrontView_1", m1)}
        assert any("matches section marks" in r.message for r in caplog.records)


class TestComputeSectionAlignment:
    # Geometry captured from a real drawing. Every view in that
    # drawing shares scale 20.0, so the mark-projection term cancels and
    # `delta` reduces to a plain origin difference on the cut axis. The
    # expected values below are therefore hand-verifiable from the origins
    # (not produced by the formula under test), e.g. section 3 on the X axis:
    # 180.9 - 203.7 = -22.8.
    @pytest.mark.parametrize(
        "child_name, mark, parent_origin, child_origin, expected_axis, expected_delta",
        [
            # section 7: horizontal cut, already aligned (164.0 - 164.0)
            ("7", StubMark((814.7, -200.8), (-2488.7, -200.8)), (164.0, 777.6), (164.0, 659.7), "x", 0.0),
            # section 3: horizontal cut, misaligned (180.9 - 203.7)
            ("3", StubMark((197.7, 1607.4), (-2144.4, 1607.4)), (180.9, 1073.8), (203.7, 960.4), "x", -22.8),
            # section 1: vertical cut, misaligned (1073.8 - 1055.4)
            ("1", StubMark((-1232.3, 1641.6), (-1232.3, -1663.4)), (180.9, 1073.8), (258.3, 1055.4), "y", 18.4),
            # section 6: vertical cut, misaligned (777.6 - 753.0)
            ("6", StubMark((-1462.0, 1703.1), (-1462.0, -1637.2)), (164.0, 777.6), (235.1, 753.0), "y", 24.6),
        ],
    )
    def test_real_drawing_geometry(self, child_name, mark, parent_origin, child_origin, expected_axis, expected_delta):
        parent = StubView("FrontView_P", "PARENT", "FrontView", origin=parent_origin, scale=20.0)
        child = StubView("SectionView_C", child_name, "SectionView", origin=child_origin, scale=20.0)
        axis, delta = compute_section_alignment(child, parent, mark)
        assert axis == expected_axis
        assert delta == pytest.approx(expected_delta, abs=0.05)

    def test_child_origin_offset_recovers_exactly(self):
        # Section 7 is aligned at origin_x=164.0 (delta 0). Moving the child a
        # known +250 mm on the cut axis must yield delta=-250 to undo it. The
        # ground truth is the chosen offset, not the formula's own output.
        mark = StubMark((814.7, -200.8), (-2488.7, -200.8))
        parent = StubView("FrontView_P", "PARENT", "FrontView", origin=(164.0, 777.6), scale=20.0)
        child = StubView("SectionView_C", "7", "SectionView", origin=(164.0 + 250.0, 659.7), scale=20.0)
        axis, delta = compute_section_alignment(child, parent, mark)
        assert axis == "x"
        assert delta == pytest.approx(-250.0, abs=0.05)

    def test_parent_origin_shift_moves_delta(self):
        # Section 1 needs delta 18.4 against parent origin_y=1073.8. Shifting
        # the parent +100 mm on the cut axis must add exactly +100 to delta.
        mark = StubMark((-1232.3, 1641.6), (-1232.3, -1663.4))
        parent = StubView("FrontView_P", "PARENT", "FrontView", origin=(180.9, 1073.8 + 100.0), scale=20.0)
        child = StubView("SectionView_C", "1", "SectionView", origin=(258.3, 1055.4), scale=20.0)
        axis, delta = compute_section_alignment(child, parent, mark)
        assert axis == "y"
        assert delta == pytest.approx(118.4, abs=0.05)

    def test_scale_projects_mark_midpoint(self):
        # Equal scales hide the projection term, so this synthetic case uses
        # DIFFERENT parent/child scales. Moving the cut midpoint by +600 mm
        # must shift the X delta by 600 * (1/parent.scale - 1/child.scale)
        # = 600 * (1/30 - 1/20) = -10.0. This pins the `mid / scale` division
        # independently of any absolute value.
        parent = StubView("FrontView_P", "PARENT", "FrontView", origin=(0.0, 0.0), scale=30.0)
        child = StubView("SectionView_C", "X", "SectionView", origin=(0.0, 0.0), scale=20.0)
        near = StubMark((300.0, 0.0), (-300.0, 0.0))  # midpoint X = 0
        far = StubMark((900.0, 0.0), (300.0, 0.0))  # midpoint X = 600
        _, delta_near = compute_section_alignment(child, parent, near)
        axis, delta_far = compute_section_alignment(child, parent, far)
        assert axis == "x"
        assert delta_far - delta_near == pytest.approx(-10.0, abs=0.05)

    def test_mark_without_endpoints_returns_none(self):
        # A mark missing LeftPoint/RightPoint cannot be projected.
        bad_mark = SimpleNamespace()
        parent = StubView("FrontView_P", "PARENT", "FrontView", origin=(0.0, 0.0), scale=20.0)
        child = StubView("SectionView_C", "1", "SectionView", origin=(0.0, 0.0), scale=20.0)
        assert compute_section_alignment(child, parent, bad_mark) is None
