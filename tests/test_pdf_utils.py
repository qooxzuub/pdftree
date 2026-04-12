"""Unit tests for pdf_utils.py — no Textual required."""

import pikepdf
import pytest

from pdftree.pdf_utils import is_content_stream, sort_pdf_keys

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
