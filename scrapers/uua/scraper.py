import requests
import re
import csv
import json
import os
import sys

BASE_URL = "https://secure.uua.org/certification-report/{year}/"
BASE_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "uua")

SQ = "'"


def fetch_page(url):
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.text


def extract_script_blocks(html):
    return re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)


def convert_single_to_double_quotes(text):
    """Walk char-by-char, converting JS single-quoted strings to JSON double-quoted."""
    result = []
    i = 0
    while i < len(text):
        if text[i] == SQ:
            j = i + 1
            content_chars = []
            while j < len(text):
                if text[j] == "\\" and j + 1 < len(text) and text[j + 1] == SQ:
                    content_chars.append(SQ)
                    j += 2
                elif text[j] == SQ:
                    break
                else:
                    content_chars.append(text[j])
                    j += 1
            content = "".join(content_chars)
            content = content.replace("\\", "\\\\")
            content = content.replace('"', '\\"')
            content = re.sub(r"<[^>]+>", "", content)
            result.append('"')
            result.append(content)
            result.append('"')
            i = j + 1
        else:
            result.append(text[i])
            i += 1
    return "".join(result)


def clean_js_array_string(s):
    """Clean a JavaScript array literal so it can be parsed as JSON."""
    s = s.strip()
    # Remove JS line comments (but not :// in URLs)
    s = re.sub(r"(?<![:\x22'])//[^\n]*", "", s)
    # Normalize whitespace (newlines inside JS strings break JSON)
    s = re.sub(r"\n\s*", " ", s)
    s = re.sub(r",\s*\]", "]", s)
    s = re.sub(r",\s*\}", "}", s)
    # {v:val, f:"formatted"} objects -- extract just the v value
    s = re.sub(r'\{v:\s*(\d+),\s*f:\s*"[^"]*"\}', r"\1", s)
    s = re.sub(r"\{v:\s*(\d+),\s*f:\s*'[^']*'\}", r"\1", s)
    # {role:"style"} and similar
    s = re.sub(r'\{role:\s*"[^"]*"\}', "null", s)
    s = re.sub(r"\{[^}]*role:\s*'[^']*'[^}]*\}", "null", s)
    # JS arithmetic expressions
    def eval_expr(match):
        expr = match.group(0)
        if "(" not in expr:
            return expr
        try:
            return str(eval(expr))
        except Exception:
            return expr
    s = re.sub(r"\d+[\-\+\*\/]+[\(\)\d\.\s\-\+\*\/]+\)", eval_expr, s)
    s = convert_single_to_double_quotes(s)
    return s


def parse_array_to_datatable(js_text):
    """Extract all arrayToDataTable([...]) calls."""
    results = []
    pattern = r"var\s+(\w+)\s*=\s*google\.visualization\.arrayToDataTable\(\s*\["
    for match in re.finditer(pattern, js_text):
        var_name = match.group(1)
        start = match.end() - 1
        bracket_depth = 0
        pos = start
        while pos < len(js_text):
            if js_text[pos] == "[":
                bracket_depth += 1
            elif js_text[pos] == "]":
                bracket_depth -= 1
                if bracket_depth == 0:
                    break
            pos += 1
        array_str = js_text[start : pos + 1]
        cleaned = clean_js_array_string(array_str)
        try:
            data = json.loads(cleaned)
            if data and isinstance(data[0], list):
                null_cols = {i for i, v in enumerate(data[0]) if v is None}
                if null_cols:
                    data = [
                        [v for i, v in enumerate(row) if i not in null_cols]
                        for row in data
                    ]
            results.append((var_name, data))
        except json.JSONDecodeError as e:
            print(
                f"  Warning: Could not parse arrayToDataTable for var "
                f"'{var_name}': {e}",
                file=sys.stderr,
            )
    return results


def parse_datatable_addrows(js_text):
    """Extract DataTable() with addColumn/addRows pattern."""
    results = []
    pattern = r"var\s+(\w+)\s*=\s*new\s+google\.visualization\.DataTable\(\)"
    for match in re.finditer(pattern, js_text):
        var_name = match.group(1)
        remaining = js_text[match.end() :]
        col_pattern = rf"{var_name}\.addColumn\([^,]+,\s*['\x22]([^'\x22]+)['\x22]\)"
        columns = re.findall(col_pattern, remaining[:2000])
        col_obj_pattern = rf"{var_name}\.addColumn\(\{{[^}}]*\}}\)"
        obj_cols = re.findall(col_obj_pattern, remaining[:2000])
        rows_match = re.search(rf"{var_name}\.addRows\(\s*\[", remaining)
        if not rows_match or not columns:
            continue
        rows_start = rows_match.end() - 1
        bracket_depth = 0
        pos = rows_start
        while pos < len(remaining):
            if remaining[pos] == "[":
                bracket_depth += 1
            elif remaining[pos] == "]":
                bracket_depth -= 1
                if bracket_depth == 0:
                    break
            pos += 1
        rows_str = remaining[rows_start : pos + 1]
        cleaned = clean_js_array_string(rows_str)
        try:
            rows = json.loads(cleaned)
            if columns:
                data = [columns] + [
                    [row[i] for i in range(min(len(columns), len(row)))]
                    for row in rows
                ]
                results.append((var_name, data))
        except json.JSONDecodeError as e:
            print(
                f"  Warning: Could not parse addRows for var "
                f"'{var_name}': {e}",
                file=sys.stderr,
            )
    return results


def find_var_to_element_mapping(js_text):
    """Map variable names to element IDs based on .draw() calls."""
    mapping = {}
    draw_pattern = re.findall(
        r"new\s+google\.visualization\.\w+\("
        r"document\.getElementById\(['\x22]([^'\x22]+)['\x22]\)\);\s*"
        r"\w+\.draw\((\w+)",
        js_text,
    )
    for element_id, var_name in draw_pattern:
        if var_name not in mapping:
            mapping[var_name] = []
        mapping[var_name].append(element_id)
    lines = js_text.split("\n")
    for i, line in enumerate(lines):
        id_match = re.search(
            r"getElementById\(['\x22]([^'\x22]+)['\x22]\)", line
        )
        if id_match:
            element_id = id_match.group(1)
            search_area = "\n".join(lines[i : i + 3])
            draw_match = re.search(r"\.draw\((\w+)", search_area)
            if draw_match:
                var_name = draw_match.group(1)
                if var_name not in mapping:
                    mapping[var_name] = []
                if element_id not in mapping[var_name]:
                    mapping[var_name].append(element_id)
    # Handle sequential: var chart = new ...Chart(getElementById('id'));
    # then: chart.draw(dataVar, ...); where chart var may be reused.
    # Process in source order to pair each draw with its preceding assignment.
    assign_pattern = (
        r"var\s+(\w+)\s*=\s*new\s+google\.visualization\.\w+\("
        r"document\.getElementById\(['\x22]([^'\x22]+)['\x22]\)\)"
    )
    draw_pat = r"(\w+)\.draw\((\w+)"
    events = []
    for m in re.finditer(assign_pattern, js_text):
        events.append((m.start(), "assign", m.group(1), m.group(2)))
    for m in re.finditer(draw_pat, js_text):
        events.append((m.start(), "draw", m.group(1), m.group(2)))
    events.sort(key=lambda x: x[0])
    chart_to_element = {}
    for _, kind, a, b in events:
        if kind == "assign":
            chart_to_element[a] = b
        elif kind == "draw" and a in chart_to_element:
            data_var = b
            eid = chart_to_element[a]
            if data_var not in mapping:
                mapping[data_var] = []
            if eid not in mapping[data_var]:
                mapping[data_var].append(eid)
    return mapping


def extract_all_tables(html):
    """Extract all tables from HTML, returns dict of {element_id: data}."""
    tables = {}
    script_blocks = extract_script_blocks(html)
    for block in script_blocks:
        if "google.visualization" not in block:
            continue
        var_to_elements = find_var_to_element_mapping(block)
        parsed_tables = parse_array_to_datatable(block)
        parsed_tables += parse_datatable_addrows(block)
        for var_name, data in parsed_tables:
            if not data:
                continue
            element_ids = var_to_elements.get(var_name, [])
            if element_ids:
                for eid in element_ids:
                    tables[eid] = data
            else:
                tables[var_name] = data
    return tables


def write_csv(table_id, data, output_dir, year):
    filepath = os.path.join(output_dir, f"{table_id}.csv")
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        header = data[0] if data else []
        writer.writerow(["report_year"] + list(header))
        for row in data[1:]:
            writer.writerow([year] + list(row))
    return filepath


def scrape_year(year):
    url = BASE_URL.format(year=year)
    output_dir = os.path.join(BASE_OUTPUT_DIR, str(year))
    print(f"Fetching {url}...")
    html = fetch_page(url)
    print(f"Fetched {len(html)} bytes")
    print("Extracting tables...")
    tables = extract_all_tables(html)
    os.makedirs(output_dir, exist_ok=True)
    print(f"\nFound {len(tables)} tables:")
    for table_id, data in sorted(tables.items()):
        rows = len(data) - 1 if data else 0
        cols = len(data[0]) if data else 0
        filepath = write_csv(table_id, data, output_dir, year)
        print(f"  {table_id}: {rows} rows x {cols} cols -> {os.path.basename(filepath)}")
    print(f"\nDone. CSVs written to {output_dir}")


def main():
    years = [int(y) for y in sys.argv[1:]] if len(sys.argv) > 1 else [2025]
    for year in years:
        scrape_year(year)
        if year != years[-1]:
            print()


if __name__ == "__main__":
    main()
