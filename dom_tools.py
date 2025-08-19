from bs4 import BeautifulSoup
from typing import List, Dict

def build_dom_inventory(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    items = []
    for el in soup.find_all(True):
        tag = el.name
        if tag in ("script","style","svg","path"):
            continue
        item = {
            "tag": tag,
            "id": el.get("id"),
            "role": el.get("role"),
            "testid": el.get("data-testid"),
            "placeholder": el.get("placeholder"),
            "label": None,
            "text": (el.get_text(strip=True) or "")[:100],
            "cssCandidates": []
        }
        if "class" in el.attrs:
            for c in el["class"]:
                if c:
                    stable = c.split("-")[0]
                    item["cssCandidates"].append(f"[class^=\"{stable}\"]")
        items.append(item)
    return items
