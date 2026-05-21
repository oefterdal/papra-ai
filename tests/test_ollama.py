import unittest

from ollama import build_analysis_prompt, parse_extracted_document


class ParseExtractedDocumentTest(unittest.TestCase):
    def test_build_analysis_prompt_loads_template_file(self) -> None:
        prompt = build_analysis_prompt(
            filename="receipt.png",
            existing_content="Total: 12.50",
            available_tags=[
                {
                    "name": "Receipt",
                }
            ],
        )

        self.assertIn("You enrich a Papra document", prompt)
        self.assertIn("receipt.png", prompt)
        self.assertIn("Total: 12.50", prompt)
        self.assertIn("- Receipt", prompt)

    def test_parse_normalizes_tags_and_defaults(self) -> None:
        extracted = parse_extracted_document(
            """
            {
              "title": "Receipt",
              "tags": [" Receipt ", "receipt", "", "a valid tag"]
            }
            """,
            fallback_title="fallback.jpg",
        )

        self.assertEqual(extracted.title, "Receipt")
        self.assertEqual(extracted.content, "")
        self.assertEqual(extracted.tags, ["Receipt", "a valid tag"])

    def test_parse_stringifies_structured_content(self) -> None:
        extracted = parse_extracted_document(
            """
            {
              "title": "Invoice",
              "content": {
                "bill_to": [{"name": "John"}],
                "invoice_date": "2018-02-02"
              },
              "tags": []
            }
            """,
            fallback_title="invoice.png",
        )

        self.assertIn('"bill_to"', extracted.content)
        self.assertIn('"John"', extracted.content)
        self.assertIn('"invoice_date"', extracted.content)

    def test_parse_extracts_tag_names_from_objects(self) -> None:
        extracted = parse_extracted_document(
            """
            {
              "title": "Catalog",
              "content": "",
              "tags": [
                {"tag-key": "#bestseller", "tag-name": "Bestseller"},
                {"tag_name": "Catalog"},
                {"unknown": "ignored"}
              ]
            }
            """,
            fallback_title="catalog.png",
        )

        self.assertEqual(extracted.tags, ["Bestseller", "Catalog"])

    def test_parse_rejects_non_json(self) -> None:
        with self.assertRaises(ValueError):
            parse_extracted_document("not json", fallback_title="fallback.jpg")


if __name__ == "__main__":
    unittest.main()
