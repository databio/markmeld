"""Templates and table PDFs cannot reach Python or local files.

On a shared server a Jinja template, or a co-author's text rendered a second
time, can come from someone else; so can a table config.
"""

import pytest
from jinja2.exceptions import SecurityError

from markmeld.figure_conversion import _refuse_fetch
from markmeld.melder import make_template


def test_templates_render_normally_with_markmeld_filters():
    tpl = make_template("{{ title }}: {% for x in items %}{{ x|upper }} {% endfor %}{{ refs|extract_refs }}")
    out = tpl.render(title="T", items=["a", "b"], refs="see @smith2020")
    assert out.startswith("T: A B ")
    assert "smith2020" in out
    assert tpl.source.startswith("{{ title }}")


@pytest.mark.parametrize(
    "attack",
    [
        "{{ ''.__class__.__mro__[1].__subclasses__() }}",
        "{{ cycler.__init__.__globals__.os.popen('id').read() }}",
        "{{ self.__init__.__globals__ }}",
    ],
)
def test_templates_cannot_reach_python(attack):
    with pytest.raises(SecurityError):
        make_template(attack).render()


def test_table_pdfs_refuse_file_and_network_urls():
    for url in ("file:///etc/passwd", "http://169.254.169.254/latest", "https://example.com/x.css"):
        with pytest.raises(ValueError, match="no outside resources"):
            _refuse_fetch(url)


def test_table_pdfs_still_accept_data_urls():
    pytest.importorskip("weasyprint")
    result = _refuse_fetch("data:text/plain,hello")
    body = result.get("string") or result["file_obj"].read()
    assert body == b"hello"
