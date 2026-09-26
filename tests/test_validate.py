from order_search.ingest.validate import is_blank, validate_rows


def make_row(**overrides):
    row = {
        "Product Name": "น้ำดื่มสิงห์ 600 มล. x 12",
        "Customer Name": "สุรชัย",
        "Bar_Code": ["8850250001234"],
        "date_from": "2026-09-26",
        "date_to": "2026-09-26",
    }
    row.update(overrides)
    return row


class TestIsBlank:
    def test_blank_values(self):
        assert is_blank(None)
        assert is_blank("")
        assert is_blank("   ")

    def test_non_blank_values(self):
        assert not is_blank("x")
        assert not is_blank(0)


class TestValidateRows:
    def test_keeps_complete_rows(self):
        rows = [make_row(), make_row()]
        usable, report = validate_rows(rows)
        assert len(usable) == 2
        assert report.skipped_rows == []
        assert report.rows_read == 2
        assert report.rows_imported == 2
        assert report.rows_skipped == 0
        assert report.products == 0
        assert report.customers == 0
        assert report.orders == 0
        assert report.barcodes == 0

    def test_skips_row_without_product_name(self):
        rows = [make_row(), make_row(**{"Product Name": ""})]
        usable, report = validate_rows(rows)
        assert len(usable) == 1
        assert report.rows_skipped == 1
        assert report.rows_imported == 1

    def test_skips_row_without_customer_name(self):
        rows = [make_row(**{"Customer Name": None})]
        usable, report = validate_rows(rows)
        assert usable == []
        assert len(report.skipped_rows) == 1

    def test_skipped_positions_are_1_based_sheet_rows(self):
        # position 1 is the header, so the first data row is sheet row 2
        rows = [
            make_row(),
            make_row(**{"Product Name": ""}),
            make_row(),
            make_row(**{"Customer Name": "  "}),
        ]
        _usable, report = validate_rows(rows)
        assert report.skipped_rows == [3, 5]

    def test_counts_rows_without_barcode(self):
        rows = [make_row(**{"Bar_Code": []}), make_row()]
        _usable, report = validate_rows(rows)
        assert report.missing_barcode_rows == 1

    def test_counts_rows_with_unparsed_date(self):
        rows = [make_row(date_from=None, date_to=None), make_row()]
        _usable, report = validate_rows(rows)
        assert report.unparsed_date_rows == 1

    def test_warning_names_only_the_missing_column(self):
        rows = [make_row(**{"Product Name": ""})]
        _usable, report = validate_rows(rows)
        assert report.warnings == ["row 2: missing Product Name"]

        rows = [make_row(**{"Customer Name": None})]
        _usable, report = validate_rows(rows)
        assert report.warnings == ["row 2: missing Customer Name"]
        assert "Product Name" not in report.warnings[0]

    def test_warning_names_both_columns_when_both_are_missing(self):
        rows = [make_row(**{"Product Name": "", "Customer Name": ""})]
        _usable, report = validate_rows(rows)
        assert report.warnings == ["row 2: missing Product Name, Customer Name"]

    def test_empty_input(self):
        usable, report = validate_rows([])
        assert usable == []
        assert report.skipped_rows == []
        assert report.rows_read == 0
        assert report.rows_imported == 0

    def test_summary_mentions_every_counter(self):
        rows = [make_row(**{"Bar_Code": [], "date_from": None, "date_to": None})]
        _usable, report = validate_rows(rows)
        summary = report.summary()
        for label in [
            "rows read",
            "rows imported",
            "rows skipped",
            "products",
            "customers",
            "orders",
            "barcodes",
            "no barcode",
            "bad date",
            "no pack size",
        ]:
            assert label in summary
