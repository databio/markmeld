"""Tests for ad-hoc input file support (--input and -o flags)"""


def test_input_file_injects_content(mm_target, tmp_path):
    """--input should inject an external file as md_files.content"""
    input_file = tmp_path / "input.md"
    input_file.write_text(
        "---\ntitle: External Letter\n---\nDear Sir,\n\nPlease accept this."
    )

    result = mm_target(
        "{{ content }}",
        build_kwargs={"input_file": str(input_file)},
    )
    assert result.melded_output
    assert "Dear Sir," in result.melded_output
    assert "Please accept this." in result.melded_output


def test_input_file_frontmatter_available(mm_target, tmp_path):
    """--input file's frontmatter should be available to the template"""
    input_file = tmp_path / "input.md"
    input_file.write_text(
        "---\ntitle: My Letter\nrecipient: Dr. Smith\n---\nBody text here."
    )

    result = mm_target(
        "To: {{ recipient }}\n{{ content }}",
        build_kwargs={"input_file": str(input_file)},
    )
    assert result.melded_output
    assert "To: Dr. Smith" in result.melded_output
    assert "Body text here." in result.melded_output


def test_output_file_override(mm_target, tmp_path):
    """--output should override the target's output_file"""
    input_file = tmp_path / "input.md"
    input_file.write_text("Content")

    result = mm_target(
        "{{ content }}",
        output_file="original.pdf",
        build_kwargs={
            "input_file": str(input_file),
            "output_file": "/tmp/custom_output.pdf",
        },
    )
    assert result.meta["output_file"] == "/tmp/custom_output.pdf"


def test_output_file_defaults_from_input(mm_target, tmp_path):
    """When --input is given without -o and target has no output_file, default to {input_stem}.pdf"""
    input_file = tmp_path / "letter_input.md"
    input_file.write_text("Content")

    result = mm_target(
        "{{ content }}",
        build_kwargs={"input_file": str(input_file)},
    )
    expected = str(input_file).replace(".md", ".pdf")
    assert result.meta["output_file"] == expected


def test_input_merges_with_existing_data(mm_target, tmp_path):
    """--input should merge with existing target data, not replace it"""
    input_file = tmp_path / "input.md"
    input_file.write_text("Letter body")

    result = mm_target(
        "Org: {{ org }}\n{{ content }}",
        data={"variables": {"org": "ACME Corp"}},
        build_kwargs={"input_file": str(input_file)},
    )
    assert result.melded_output
    assert "Org: ACME Corp" in result.melded_output
    assert "Letter body" in result.melded_output
