import os
import sys
from pathlib import Path
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from retrofit_sidebar import retrofit_sidebar


def test_retrofit_sidebar(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "module_a.py").write_text("# sample\n", encoding="utf-8")
    pkg = src / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("# init\n", encoding="utf-8")
    (pkg / "submodule.py").write_text("# sub\n", encoding="utf-8")

    docs = tmp_path / "docs"
    docs.mkdir()
    html_path = docs / "page.html"
    html_content = (
        "<html><body><div class='sidebar'><p>Old sidebar</p></div>"
        "<div class='content'><p>Main content</p></div></body></html>"
    )
    html_path.write_text(html_content, encoding="utf-8")
    original_main = BeautifulSoup(html_content, "html.parser").find(
        "div", class_="content"
    ).decode()

    retrofit_sidebar(str(src), str(docs))

    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    sidebar = soup.find("div", class_="sidebar")
    ul = sidebar.find("ul", recursive=False)
    top_items = ul.find_all("li", recursive=False)

    module_link = top_items[0].find("a", recursive=False)
    assert module_link is not None
    assert module_link["href"] == "module_a.html"
    assert module_link.string == "module_a.py"

    pkg_li = top_items[1]
    assert pkg_li.contents[0] == "pkg"
    pkg_ul = pkg_li.find("ul", recursive=False)
    pkg_items = pkg_ul.find_all("li", recursive=False)
    pkg_links = [li.find("a", recursive=False) for li in pkg_items]
    assert [link.string for link in pkg_links] == ["__init__.py", "submodule.py"]
    assert [link["href"] for link in pkg_links] == [
        "pkg/__init__.html",
        "pkg/submodule.html",
    ]

    assert soup.find("div", class_="content").decode() == original_main
