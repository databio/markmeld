"""Tests for the `mm csv2pdf` subcommand."""

import textwrap

import pytest

from markmeld.cli import csv2pdf_main


@pytest.fixture
def sample_csv(tmp_path):
    csv_file = tmp_path / "table.csv"
    csv_file.write_text(textwrap.dedent("""\
        Category,Count,Percentage
        Alpha,10,25
        Beta,20,50
        Gamma,10,25
    """))
    return csv_file


def test_csv2pdf_basic(tmp_path, sample_csv):
    output = tmp_path / "out.pdf"
    rc = csv2pdf_main([str(sample_csv), str(output)])
    assert rc == 0
    assert output.exists()
    assert output.read_bytes().startswith(b"%PDF")


def test_csv2pdf_with_options(tmp_path, sample_csv):
    output = tmp_path / "out.pdf"
    rc = csv2pdf_main([
        str(sample_csv), str(output),
        "--width", "174mm",
        "--font-size", "7pt",
        "--col-widths", "20,30,50",
        "--col-align", "left,center,right",
        "--col-names", "Name,Num,Pct",
    ])
    assert rc == 0
    assert output.exists()
    assert output.read_bytes().startswith(b"%PDF")


def test_csv2pdf_creates_parent_dir(tmp_path, sample_csv):
    output = tmp_path / "nested" / "sub" / "out.pdf"
    rc = csv2pdf_main([str(sample_csv), str(output)])
    assert rc == 0
    assert output.exists()


def test_csv2pdf_missing_input(tmp_path):
    output = tmp_path / "out.pdf"
    with pytest.raises(FileNotFoundError):
        csv2pdf_main([str(tmp_path / "nonexistent.csv"), str(output)])
