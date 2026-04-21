"""Unit tests for pdf_utils.py — no Textual required."""

import pikepdf
import pytest

from pdftree.pdf_utils import (
    is_content_stream,
    sort_pdf_keys,
    JumpReference,
    DeferredJumpReference,
    TreeAdapter,
    walk_pdf,
    disassemble_content_stream,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def pdf():
    """A bare in-memory PDF — used only to own stream objects."""
    return pikepdf.Pdf.new()


def make_stream(pdf, data=b"BT ET", **keys):
    """Create a pikepdf.Stream with optional dictionary keys."""
    s = pikepdf.Stream(pdf, data)
    for k, v in keys.items():
        s[f"/{k}"] = v
    return s


# ---------------------------------------------------------------------------
# is_content_stream — name-based detection
# ---------------------------------------------------------------------------


class TestIsContentStreamByName:
    def test_contents_direct(self, pdf):
        """A stream named /Contents is always a content stream."""
        s = make_stream(pdf)
        assert is_content_stream(s, "/Contents") is True

    def test_contents_array_element(self, pdf):
        """Array elements of a /Contents array are content streams."""
        s = make_stream(pdf)
        assert is_content_stream(s, "[0]", parent_name="/Contents") is True
        assert is_content_stream(s, "[1]", parent_name="/Contents") is True
        assert is_content_stream(s, "[99]", parent_name="/Contents") is True

    def test_appearance_stream_N(self, pdf):
        s = make_stream(pdf)
        assert is_content_stream(s, "/N") is True

    def test_appearance_stream_R(self, pdf):
        s = make_stream(pdf)
        assert is_content_stream(s, "/R") is True

    def test_appearance_stream_D(self, pdf):
        s = make_stream(pdf)
        assert is_content_stream(s, "/D") is True

    def test_appearance_stream_only_without_type(self, pdf):
        """/N with an explicit /Type should NOT match the appearance heuristic."""
        s = make_stream(pdf, Type=pikepdf.Name("/XObject"))
        # Has a /Type so it's not an anonymous appearance stream
        assert is_content_stream(s, "/N") is False

    def test_arbitrary_name_not_content(self, pdf):
        s = make_stream(pdf)
        assert is_content_stream(s, "/foo") is False
        assert is_content_stream(s, "/Length") is False
        assert is_content_stream(s, "[0]") is False  # no parent_name


# ---------------------------------------------------------------------------
# is_content_stream — type-based detection
# ---------------------------------------------------------------------------


class TestIsContentStreamByType:
    def test_form_xobject(self, pdf):
        s = make_stream(
            pdf,
            Type=pikepdf.Name("/XObject"),
            Subtype=pikepdf.Name("/Form"),
        )
        assert is_content_stream(s, "/Fm0") is True

    def test_image_xobject_not_content(self, pdf):
        s = make_stream(
            pdf,
            Type=pikepdf.Name("/XObject"),
            Subtype=pikepdf.Name("/Image"),
        )
        assert is_content_stream(s, "/Im0") is False

    def test_xobject_without_subtype_not_content(self, pdf):
        s = make_stream(pdf, Type=pikepdf.Name("/XObject"))
        assert is_content_stream(s, "/X0") is False

    def test_pattern_stream(self, pdf):
        s = make_stream(pdf, Type=pikepdf.Name("/Pattern"))
        assert is_content_stream(s, "/P1") is True

    def test_objstm_not_content(self, pdf):
        s = make_stream(pdf, Type=pikepdf.Name("/ObjStm"))
        assert is_content_stream(s, "/ObjStm") is False

    def test_metadata_not_content(self, pdf):
        s = make_stream(pdf, Type=pikepdf.Name("/Metadata"))
        assert is_content_stream(s, "/Metadata") is False

    def test_xref_not_content(self, pdf):
        s = make_stream(pdf, Type=pikepdf.Name("/XRef"))
        assert is_content_stream(s, "/XRef") is False


# ---------------------------------------------------------------------------
# is_content_stream — image filter fast-exit
# ---------------------------------------------------------------------------


class TestIsContentStreamImageFilters:
    @pytest.mark.parametrize(
        "filter_name",
        [
            "/DCTDecode",
            "/JPXDecode",
            "/CCITTFaxDecode",
            "/JBIG2Decode",
        ],
    )
    def test_image_filter_blocks_content(self, pdf, filter_name):
        """/Contents streams with image codecs are NOT content streams."""
        s = make_stream(pdf, Filter=pikepdf.Name(filter_name))
        assert is_content_stream(s, "/Contents") is False

    def test_flate_decode_is_fine(self, pdf):
        """/FlateDecode is the normal compression for content streams."""
        s = make_stream(pdf, Filter=pikepdf.Name("/FlateDecode"))
        assert is_content_stream(s, "/Contents") is True

    def test_array_filter_with_image_codec_blocked(self, pdf):
        """If any filter in an array is an image codec, block it."""
        s = make_stream(
            pdf,
            Filter=pikepdf.Array(
                [
                    pikepdf.Name("/FlateDecode"),
                    pikepdf.Name("/DCTDecode"),
                ]
            ),
        )
        assert is_content_stream(s, "/Contents") is False

    def test_array_filter_flate_only_ok(self, pdf):
        s = make_stream(
            pdf,
            Filter=pikepdf.Array([pikepdf.Name("/FlateDecode")]),
        )
        assert is_content_stream(s, "/Contents") is True

    def test_image_filter_overrides_form_xobject(self, pdf):
        """Even a Form XObject with a JPEG filter should be blocked."""
        s = make_stream(
            pdf,
            Type=pikepdf.Name("/XObject"),
            Subtype=pikepdf.Name("/Form"),
            Filter=pikepdf.Name("/DCTDecode"),
        )
        assert is_content_stream(s, "/Fm0") is False


# ---------------------------------------------------------------------------
# sort_pdf_keys
# ---------------------------------------------------------------------------


class TestSortPdfKeys:
    def test_type_sorts_first(self):
        items = [
            ("/Other", pikepdf.Name("/Val")),
            ("/Type", pikepdf.Name("/Page")),
            ("/Alpha", pikepdf.Name("/Val")),
        ]
        sorted_items = sorted(items, key=sort_pdf_keys)
        assert sorted_items[0][0] == "/Type"

    def test_backbone_keys_sort_early(self):
        items = [
            ("/Zebra", pikepdf.Name("/Val")),
            ("/Root", pikepdf.Name("/Val")),
            ("/Pages", pikepdf.Name("/Val")),
            ("/Kids", pikepdf.Name("/Val")),
        ]
        sorted_items = sorted(items, key=sort_pdf_keys)
        names = [k for k, _ in sorted_items]
        assert names[0] in ("/Kids", "/Pages", "/Root")
        assert "Zebra" not in names[:3]

    def test_composites_sort_after_primitives(self):
        items = [
            ("/Alpha", pikepdf.Name("/Val")),  # primitive
            ("/Beta", pikepdf.Dictionary()),  # composite
            ("/Gamma", pikepdf.Name("/Val")),  # primitive
            ("/Delta", pikepdf.Array()),  # composite
        ]
        sorted_items = sorted(items, key=sort_pdf_keys)
        keys = [k for k, _ in sorted_items]
        # All primitives before composites
        primitive_indices = [keys.index("/Alpha"), keys.index("/Gamma")]
        composite_indices = [keys.index("/Beta"), keys.index("/Delta")]
        assert max(primitive_indices) < min(composite_indices)

    def test_alphabetical_tiebreak(self):
        items = [
            ("/Zebra", pikepdf.Name("/Val")),
            ("/Apple", pikepdf.Name("/Val")),
            ("/Mango", pikepdf.Name("/Val")),
        ]
        sorted_items = sorted(items, key=sort_pdf_keys)
        keys = [k for k, _ in sorted_items]
        assert keys == ["/Apple", "/Mango", "/Zebra"]

    def test_type_before_backbone_before_primitives_before_composites(self):
        items = [
            ("/Pages", pikepdf.Dictionary()),  # backbone + composite
            ("/Type", pikepdf.Name("/Page")),  # /Type special
            ("/MediaBox", pikepdf.Array()),  # composite
            ("/Rotate", pikepdf.Name("/Val")),  # primitive
        ]
        sorted_items = sorted(items, key=sort_pdf_keys)
        keys = [k for k, _ in sorted_items]
        assert keys[0] == "/Type"
        assert keys[1] == "/Pages"
        assert keys[2] == "/Rotate"
        assert keys[3] == "/MediaBox"


# ==========================================
# 1. Base Class Tests (Lines 51-77)
# ==========================================


def test_jump_reference_classes():
    """Hits lines 51-61: Basic initialization of reference containers."""
    jr = JumpReference("target_node_1")
    assert jr.target_node == "target_node_1"

    djr = DeferredJumpReference("pdf_obj_1", "original_name")
    assert djr.pdf_obj == "pdf_obj_1"
    assert djr.original_name == "original_name"


def test_tree_adapter_interface():
    """Hits lines 64-77: Ensure the base interface doesn't throw errors."""
    adapter = TreeAdapter()
    # These just pass, but calling them marks them as covered
    adapter.create_node(None, None, "name", "type")
    adapter.create_jump(None, None, "name")
    adapter.create_deferred(None, None, "name")
    adapter.resolve_deferred(None, None, "name", False)


# ==========================================
# 2. walk_pdf Traversal Tests (Lines 80-159)
# ==========================================


class MockAdapter(TreeAdapter):
    """A dummy adapter that records what walk_pdf tells it to do."""

    def __init__(self):
        self.nodes = []
        self.jumps = []
        self.deferred = []
        self.resolved = []
        self.backlinks = {}

    def create_node(self, parent, pdf_obj, name, label_type):
        self.nodes.append((name, label_type))
        return f"ui_{name}"

    def create_jump(self, parent, target_node, name):
        self.jumps.append(name)

    def create_deferred(self, parent, pdf_obj, name):
        self.deferred.append(name)
        return f"ui_deferred_{name}"

    def resolve_deferred(self, deferred_node, target_node, name, is_orphan):
        self.resolved.append((name, is_orphan))


def test_walk_pdf_basic_and_cycles():
    """Hits lines 80-135: Basic traversal and Jump (cycle) detection."""
    pdf = pikepdf.Pdf.new()

    # Create a manual cycle to trigger the Jump logic (Line 100-102)
    dict1 = pdf.make_indirect(pikepdf.Dictionary(Name="/Node1"))
    dict2 = pdf.make_indirect(pikepdf.Dictionary(Name="/Node2"))
    dict1.Child = dict2
    dict2.Parent = dict1  # Cycle!

    adapter = MockAdapter()
    walk_pdf(dict1, adapter, name="Root")

    # Verify nodes were created
    created_names = [n[0] for n in adapter.nodes]
    assert "Root" in created_names
    assert "/Child" in created_names

    # Verify the cycle was caught and turned into a JumpReference
    assert "/Parent" in adapter.jumps

    # Verify backlinks dictionary was populated (Line 158-159)
    assert len(adapter.backlinks) > 0


def test_walk_pdf_orphans_and_deferred():
    """Hits lines 104-109 and 137-156: Phase 2 Orphan recovery."""
    pdf = pikepdf.Pdf.new()

    # Create a Page object that is NOT part of a /Kids array
    # This triggers the 'is_orphan' logic.
    orphan_page = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Page))
    root = pdf.make_indirect(pikepdf.Dictionary(MyOrphan=orphan_page))

    adapter = MockAdapter()
    walk_pdf(root, adapter, name="Root")

    # Verify it was deferred initially (Line 107-109)
    assert "MyOrphan" in adapter.deferred

    # Verify Phase 2 promoted it to an orphan (Line 147-150)
    # is_orphan should be True
    assert ("MyOrphan", True) in adapter.resolved


# ==========================================
# 3. Disassembler Tests (Lines 162-189)
# ==========================================


def test_disassemble_content_stream():
    """Hits lines 162-189: Validates operand formatting and parenthesis injection."""
    pdf = pikepdf.Pdf.new()

    # Create a raw stream containing numbers, operators, and a string
    # 10 20 Td
    # (Hello PDF) Tj
    raw_content = b"10 20 Td\n(Hello PDF) Tj"
    stream = pikepdf.Stream(pdf, raw_content)

    output = disassemble_content_stream(stream)

    # Assert standard operands are aligned
    assert "10 20" in output
    assert "Td " in output

    # Assert strings had their parenthesis added back (Lines 177-179)
    assert "(Hello PDF)" in output
    assert "Tj " in output

    # Assert that comments were fetched from the 'ops' dictionary (Lines 171-172)
    # 'Td' description: 'Move text position'
    assert "% Move text position" in output
    # 'Tj' description: 'Show text'
    assert "% Show text" in output


def test_walk_pdf_orphans_and_deferred():
    """Hits lines 104-109 and 137-156: Phase 2 Orphan recovery."""
    pdf = pikepdf.Pdf.new()

    # Create a Page object that is NOT part of a /Kids array
    # This triggers the 'is_orphan' logic.
    orphan_page = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Page))
    root = pdf.make_indirect(pikepdf.Dictionary(MyOrphan=orphan_page))

    adapter = MockAdapter()
    walk_pdf(root, adapter, name="Root")

    # FIX: pikepdf dictionary keys always include the leading slash
    assert "/MyOrphan" in adapter.deferred
    assert ("/MyOrphan", True) in adapter.resolved


def test_walk_pdf_resolved_deferred():
    """Hits lines 143-146: Happy path for deferred pages found later."""
    pdf = pikepdf.Pdf.new()

    # Standard page tree structure: a Page referenced by Root, but also inside Kids
    page = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Page))
    kids_array = pdf.make_indirect(pikepdf.Array([page]))

    # FIX: walk_pdf sorts keys. /Kids gets priority 0, standard keys get 2.
    # We abuse the /Type key (priority -1) so it sorts first, appends last,
    # and pops FIRST. This guarantees it is deferred before /Kids is parsed.
    root = pdf.make_indirect(pikepdf.Dictionary(Type=page, Kids=kids_array))

    adapter = MockAdapter()
    walk_pdf(root, adapter, name="Root")

    # The /Type reference should be resolved as a Jump (is_orphan=False)
    # because it was found legally inside /Kids a moment later.
    assert ("/Type", False) in adapter.resolved


def test_walk_pdf_stream_node():
    """Hits line 117: Stream node creation."""
    pdf = pikepdf.Pdf.new()

    # Create a raw stream to ensure it triggers the Stream node_type
    stream = pdf.make_indirect(pikepdf.Stream(pdf, b"stream data"))
    root = pdf.make_indirect(pikepdf.Dictionary(MyStream=stream))

    adapter = MockAdapter()
    walk_pdf(root, adapter, name="Root")

    # Verify a Stream node was created
    created_types = [n[1] for n in adapter.nodes]
    assert "Stream" in created_types
