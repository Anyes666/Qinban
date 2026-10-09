"""All XLSX fixtures are self-authored metadata, not music."""
import io, unittest, zipfile
from discover_pop_metadata import parse_index, build_report


def fixture(rows=None, extra=""):
    rows = rows or [("001", "Test title", "Test singer")]
    cells = lambda items, r: "".join(f'<c r="{col}{r}" t="inlineStr"><is><t>{value}</t></is></c>' for col, value in zip("ABC", items))
    body = '<row r="1">'+cells(("song_id", "name", "artist"), 1)+'</row>'
    body += "".join(f'<row r="{i}">'+cells(row, i)+"</row>" for i, row in enumerate(rows,2))
    xml = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+body+extra+'</sheetData></worksheet>'
    stream = io.BytesIO()
    with zipfile.ZipFile(stream,"w") as z: z.writestr("xl/worksheets/sheet1.xml", xml)
    return stream.getvalue()


class MetadataIndexTests(unittest.TestCase):
    def test_metadata_only_with_no_language_inference(self):
        report=build_report(fixture()); row=report["candidates"][0]
        self.assertEqual(row["artists"],["Test singer"]);self.assertEqual(row["languageTags"],[])
        self.assertEqual(report["realScoresObtained"],0);self.assertEqual(report["verifiedDifferentWorks"],0)
        self.assertEqual(row["notationStatus"],"not-acquired");self.assertIsNone(row["verifiedWorkId"])
    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):parse_index(fixture([("001","A","X"),("001","B","Y")]))
    def test_title_artist_pairs_do_not_increase_verified_work_count(self):
        result=build_report(fixture([("001","A","X"),("002","A","X"),("003","A","Y")]))
        self.assertEqual(result["candidateRows"],3);self.assertEqual(result["distinctTitleArtistPairs"],2)
        self.assertEqual(result["verifiedDifferentWorks"],0)
    def test_empty_fields_and_invalid_id_rejected(self):
        for row in [("1","A","X"),("001","","X"),("001","A","")]:
            with self.subTest(row=row),self.assertRaises(ValueError):parse_index(fixture([row]))
    def test_formula_and_bad_archive_rejected(self):
        with self.assertRaises(ValueError):parse_index(fixture(extra='<row r="3"><c r="A3"><f>1+1</f><v>2</v></c></row>'))
        with self.assertRaises(zipfile.BadZipFile):parse_index(b"not xlsx")
    def test_size_budget_rejected(self):
        with self.assertRaises(ValueError):parse_index(b"x"*(1024*1024+1))


if __name__ == "__main__":unittest.main()
