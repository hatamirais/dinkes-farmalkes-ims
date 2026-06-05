"""
Fix base.html safely:
1. Remove the orphaned {% endif %} at line 165 (1-indexed)
2. Add the Rekap Laporan Persediaan link after report_persediaan link (around line 244)

Uses binary read/write to preserve exact original line endings.
"""

path = r'd:/projects/dinkes-farmalkes-ims/backend/templates/base.html'

# Read raw bytes, split on \r\n (CRLF) to preserve original encoding
with open(path, 'rb') as f:
    raw = f.read()

# Detect line ending style
if b'\r\n' in raw:
    sep = b'\r\n'
    print("Line ending: CRLF")
else:
    sep = b'\n'
    print("Line ending: LF")

lines = raw.split(sep)
print(f"Total lines: {len(lines)}")

# Print lines around 163-167 to confirm the orphaned endif location
print("\n--- Lines 161-168 (0-indexed 160-167) ---")
for i in range(160, 168):
    print(f"Line {i+1}: {lines[i].decode('utf-8', errors='replace')!r}")

# Find the exact line number of the orphaned endif
# After </div> closing the pengeluaran submenu and the first {% endif %}
# we expect a second {% endif %} that is orphaned
orphaned_idx = None
for i in range(160, 170):
    decoded = lines[i].decode('utf-8', errors='replace').strip()
    prev = lines[i-1].decode('utf-8', errors='replace').strip()
    # Looking for: prev line is '{% endif %}' (closes pengeluaran if)
    # and current line is also '{% endif %}' (orphaned)
    # and next line is empty or {% if can_view_stock %}
    if decoded == '{% endif %}' and prev == '{% endif %}':
        nxt = lines[i+1].decode('utf-8', errors='replace').strip()
        if '{% if can_view_stock %}' in nxt or nxt == '':
            orphaned_idx = i
            print(f"\nFound orphaned endif at line {i+1} (0-indexed {i})")
            break

if orphaned_idx is None:
    print("ERROR: Could not find orphaned endif! Manual inspection needed.")
else:
    # Remove the orphaned line
    lines.pop(orphaned_idx)
    print(f"Removed line {orphaned_idx+1}")

print(f"Lines after fix 1: {len(lines)}")

# Now find the report_persediaan link closing </a> and add Rekap link after it
# Pattern: find the line with <i class="bi bi-boxes"></i><span>Laporan Persediaan</span>
# then add the new Rekap link after the closing </a>
target_span = b'<i class="bi bi-boxes"></i><span>Laporan Persediaan</span>'
persediaan_a_close_idx = None
for i, line in enumerate(lines):
    if target_span in line:
        # Next line should be </a>
        if i+1 < len(lines) and b'</a>' in lines[i+1]:
            persediaan_a_close_idx = i+1
            print(f"\nFound Laporan Persediaan </a> at line {persediaan_a_close_idx+1}")
            break

if persediaan_a_close_idx is None:
    print("ERROR: Could not find Laporan Persediaan closing </a>")
else:
    # Determine indentation from the existing link
    indent = b'                    '  # 20 spaces - match existing style
    
    rekap_lines = [
        indent + b'<a href="{% url \'puskesmas:report_rekap_persediaan\' %}"',
        indent + b'    class="sidebar-link {% if request.resolver_match.url_name == \'report_rekap_persediaan\' %}active{% endif %}"',
        indent + b'    data-label="Rekap Laporan Persediaan"',
        indent + b'    title="Rekap Laporan Persediaan">',
        indent + b'    <i class="bi bi-table"></i><span>Rekap Laporan Persediaan</span>',
        indent + b'</a>',
    ]
    
    # Insert after the </a> line of report_persediaan
    for j, rekap_line in enumerate(rekap_lines):
        lines.insert(persediaan_a_close_idx + 1 + j, rekap_line)
    
    print(f"Inserted {len(rekap_lines)} new lines after line {persediaan_a_close_idx+1}")

print(f"Lines after fix 2: {len(lines)}")

# Write back with original line endings, original encoding
new_raw = sep.join(lines)
with open(path, 'wb') as f:
    f.write(new_raw)

print(f"\nDone. Wrote {len(new_raw)} bytes (was {len(raw)} bytes)")

# Verify by showing the modified section
print("\n--- Verification: new puskesmas laporan submenu ---")
with open(path, 'rb') as f:
    new_raw2 = f.read()
new_lines = new_raw2.split(sep)
for i, line in enumerate(new_lines):
    if b'report_persediaan' in line or b'report_rekap_persediaan' in line or b'Rekap Laporan' in line:
        print(f"Line {i+1}: {line.decode('utf-8', errors='replace').rstrip()}")
