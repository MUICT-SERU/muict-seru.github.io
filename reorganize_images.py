#!/usr/bin/env python3
"""
Reorganize images for SE@ICT Mahidol Google Sites export.
Steps:
  1. Parse all HTML files, extract all local image references with context.
  2. Build a mapping: old_path -> images/new-name.jpg
  3. Print the mapping for review.
  4. Create images/ directory and copy files there.
  5. Update all HTML files with new paths.
  6. Verify no old hash paths remain.
  7. Delete old per-page image directories.
"""

import os
import re
import shutil
from urllib.parse import unquote

BASE = '/Users/chaiyong/Downloads/Takeout/web'
IMAGES_DIR = os.path.join(BASE, 'images')

PAGES = [
    'About Us', 'Activities', 'Awards', 'Graduated Students', 'Home',
    'Internship Students', 'Join Us', 'News', 'Projects', 'Publications',
    'Seminars', 'Team', 'Tools'
]

PAGE_SLUGS = {
    'About Us': 'about-us',
    'Activities': 'activities',
    'Awards': 'awards',
    'Graduated Students': 'graduated-students',
    'Home': 'home',
    'Internship Students': 'internship-students',
    'Join Us': 'join-us',
    'News': 'news',
    'Projects': 'projects',
    'Publications': 'publications',
    'Seminars': 'seminars',
    'Team': 'team',
    'Tools': 'tools',
}

# Stop words for person name extraction
PERSON_STOP_WORDS = {
    'advisor', 'advisors', 'topic', 'assistant', 'professor', 'lecturer',
    'dr', 'phd', 'ms', 'mr', 'research', 'graduated', 'internship',
    'and', 'or', 'the', 'a', 'an', 'in', 'at', 'of', 'by', 'no',
}


def slugify(text, max_len=55):
    """Convert text to a slug: lowercase, hyphens, no special chars."""
    text = text.lower().strip()
    text = re.sub(r"['''`]", '', text)
    text = re.sub(r'[^a-z0-9\s-]', ' ', text)
    text = re.sub(r'\s+', '-', text)
    text = re.sub(r'-+', '-', text)
    text = text.strip('-')
    return text[:max_len].rstrip('-')


def get_text_after_img_tag(content, src_ref, search_chars=2000):
    """
    Find src_ref in content, skip to end of the img tag (closing >),
    then return plain text of next search_chars characters.
    """
    pos = content.find(f'src="{src_ref}"')
    if pos < 0:
        return ''
    # Find the closing > of this img tag
    tag_end = content.find('>', pos)
    if tag_end < 0:
        return ''
    # Get text from after the closing >
    chunk = content[tag_end + 1: tag_end + 1 + search_chars]
    # Strip HTML tags
    text = re.sub(r'<[^>]+>', ' ', chunk)
    # Decode HTML entities
    text = re.sub(r'&#39;', "'", text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_person_name(text, max_words=3):
    """
    Extract person name from text like 'Firstname Lastname (Assistant Professor)...'
    Stops at stop words or parentheses.
    Returns slugified name or empty string.
    """
    stop_html = {'class=', 'style=', 'href=', '<div', '</div', '<span', '<p', 'classxqqf9c'}

    words = text.split()
    name_parts = []
    for w in words:
        if w.startswith('(') or w.startswith('<') or w.startswith('='):
            break
        w_lower = w.lower().rstrip('.,;:')
        # Stop at HTML artifacts
        if any(tok in w_lower for tok in stop_html):
            break
        if w_lower in PERSON_STOP_WORDS:
            break
        if any(sw in w_lower for sw in ['graduated', 'advisor', 'topic', 'intern', 'asst', 'assoc']):
            break
        # Only keep words that look like names (start with uppercase or are purely alpha)
        w_clean = re.sub(r'[^a-zA-Z\-]', '', w)
        if not w_clean or len(w_clean) < 2:
            break
        name_parts.append(w_clean)
        if len(name_parts) >= max_words:
            break

    if len(name_parts) < 1:
        return ''
    return slugify(' '.join(name_parts))


def extract_content_description(text, max_words=5):
    """
    Extract a short description from text following an image.
    Used for content/article images.
    """
    # Remove URLs
    text = re.sub(r'https?://\S+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    # Stop at HTML residue (unclosed tags leaked through)
    # The huge div class strings get truncated, leaving "class=" etc.
    stop_tokens = {'class=', 'style=', 'href=', 'classxqqf9c', 'classc9dxtc', 'dirltr',
                   'classxqq', 'classjnd', 'classtyjctd', '<div', '</div', '<span', '<p'}

    words = text.split()
    desc_parts = []
    for w in words[:25]:
        w_lower = w.lower()
        # Stop if we hit an HTML artifact
        if any(tok in w_lower for tok in stop_tokens):
            break
        if w.startswith('<') or w.startswith('='):
            break
        w_clean = re.sub(r"[^a-zA-Z0-9'\-]", '', w)
        if len(w_clean) < 2:
            continue
        desc_parts.append(w_clean)
        if len(desc_parts) >= max_words:
            break

    if not desc_parts:
        return ''
    return slugify(' '.join(desc_parts))


def get_file_extension(path):
    _, ext = os.path.splitext(path.lower())
    return ext if ext else '.jpg'


def build_mapping():
    """
    Build the mapping: original_path_in_html -> new filename (without images/ prefix).
    Returns:
        mapping: dict of original_path -> new_filename_in_images_dir
        disk_paths: dict of original_path -> actual disk file path
    """
    used_names = set()

    def assign_name(base_name, ext='.jpg'):
        """Assign a unique name, appending -2, -3 etc. if needed."""
        candidate = base_name + ext
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        n = 2
        while True:
            candidate2 = f"{base_name}-{n}{ext}"
            if candidate2 not in used_names:
                used_names.add(candidate2)
                return candidate2
            n += 1

    mapping = {}     # html_path_string -> new_filename
    disk_paths = {}  # html_path_string -> actual disk file path

    # -------------------------------------------------------------------------
    # Root-level images (referenced bare, no folder prefix)
    # -------------------------------------------------------------------------
    root_images_info = {
        '026a20d61747407be1b18d1f64f4f6c5.jpg': 'favicon',
        '7e1d086435987d64316f262c0e53c9bd.jpg': 'site-logo',
        '1e06589743a64710f7d7408c3c5f673f.jpg': 'site-image-1',
        '999b55275780458abc8012236997c7a5.jpg': 'site-image-2',
    }

    for root_img, base_name in root_images_info.items():
        disk_path = os.path.join(BASE, root_img)
        if os.path.exists(disk_path):
            ext = get_file_extension(root_img)
            new_name = assign_name(base_name, ext)
            mapping[root_img] = new_name
            disk_paths[root_img] = disk_path

    # -------------------------------------------------------------------------
    # Process each page
    # -------------------------------------------------------------------------
    for page in PAGES:
        slug = PAGE_SLUGS[page]
        html_path = os.path.join(BASE, f"{page}.html")
        folder_encoded = page.replace(' ', '%20')
        folder_plain = page

        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Pages with person photos
        person_pages = {'Team', 'Graduated Students', 'Internship Students'}
        is_person_page = page in person_pages

        # --- Banner images (background-image: url(...)) ---
        bg_pattern = re.compile(r'url\(([^)]+\.(jpg|jpeg|png|gif|webp))\)', re.IGNORECASE)
        banner_count = 0

        for m in bg_pattern.finditer(content):
            bg_ref = m.group(1)
            if bg_ref.startswith('http') or bg_ref.startswith('//'):
                continue
            decoded = unquote(bg_ref)
            if not (decoded.startswith(folder_plain + '/') or decoded.startswith(folder_encoded + '/')):
                continue
            if bg_ref in mapping:
                continue

            disk_path = os.path.join(BASE, decoded)
            if not os.path.exists(disk_path):
                print(f"  WARNING: not found: {disk_path}")
                continue

            ext = get_file_extension(bg_ref)
            banner_count += 1
            if banner_count == 1:
                base_name = f"{slug}-banner"
            else:
                base_name = f"{slug}-banner-{banner_count}"

            new_name = assign_name(base_name, ext)
            mapping[bg_ref] = new_name
            disk_paths[bg_ref] = disk_path

        # --- img src images ---
        img_pattern = re.compile(r'src="([^"]+\.(jpg|jpeg|png|gif|webp))"', re.IGNORECASE)

        for m in img_pattern.finditer(content):
            img_ref = m.group(1)
            if img_ref.startswith('http') or img_ref.startswith('//'):
                continue
            if '/' not in img_ref:
                continue  # root-level, already handled

            decoded = unquote(img_ref)
            if not (decoded.startswith(folder_plain + '/') or decoded.startswith(folder_encoded + '/')):
                continue
            if img_ref in mapping:
                continue

            disk_path = os.path.join(BASE, decoded)
            if not os.path.exists(disk_path):
                print(f"  WARNING: not found: {disk_path}")
                continue

            ext = get_file_extension(img_ref)

            # Get text context (after the closing > of the img tag)
            text = get_text_after_img_tag(content, img_ref)

            if is_person_page:
                name = extract_person_name(text, max_words=3)
                if name and len(name) >= 3:
                    base_name = f"{slug}-{name}"
                else:
                    base_name = f"{slug}"
            else:
                desc = extract_content_description(text, max_words=5)
                if desc and len(desc) >= 3:
                    base_name = f"{slug}-{desc}"
                else:
                    base_name = f"{slug}"

            new_name = assign_name(base_name, ext)
            mapping[img_ref] = new_name
            disk_paths[img_ref] = disk_path

    return mapping, disk_paths


def print_mapping(mapping):
    print("\n" + "="*70)
    print("MAPPING: old_path -> images/new_name")
    print("="*70)
    for old, new in sorted(mapping.items()):
        print(f"  {old}")
        print(f"    -> images/{new}")
    print(f"\nTotal: {len(mapping)} images\n")


def create_images_dir():
    os.makedirs(IMAGES_DIR, exist_ok=True)
    print(f"Created directory: {IMAGES_DIR}")


def copy_images(mapping, disk_paths):
    print("\nCopying images...")
    copied = 0
    errors = 0
    for old_ref, new_name in mapping.items():
        src = disk_paths.get(old_ref)
        if not src:
            print(f"  ERROR: no disk path for {old_ref}")
            errors += 1
            continue
        dst = os.path.join(IMAGES_DIR, new_name)
        try:
            shutil.copy2(src, dst)
            copied += 1
        except Exception as e:
            print(f"  ERROR copying {src} -> {dst}: {e}")
            errors += 1
    print(f"  Copied: {copied}, Errors: {errors}")


def update_html_files(mapping):
    print("\nUpdating HTML files...")

    # Sort by length of old path (longest first) to avoid partial-match issues
    replacements = sorted(mapping.items(), key=lambda x: len(x[0]), reverse=True)

    for page in PAGES:
        html_path = os.path.join(BASE, f"{page}.html")
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content
        changes = 0

        for old_ref, new_name in replacements:
            new_ref = f"images/{new_name}"

            # Replace in src="..." form
            old_q = f'src="{old_ref}"'
            new_q = f'src="{new_ref}"'
            c = content.count(old_q)
            if c:
                content = content.replace(old_q, new_q)
                changes += c

            # Replace in url(...) form
            old_u = f'url({old_ref})'
            new_u = f'url({new_ref})'
            c = content.count(old_u)
            if c:
                content = content.replace(old_u, new_u)
                changes += c

            # Replace in href="..." (favicon <link rel="icon">)
            old_h = f'href="{old_ref}"'
            new_h = f'href="{new_ref}"'
            c = content.count(old_h)
            if c:
                content = content.replace(old_h, new_h)
                changes += c

            # Replace in JS string literals with escaped slash: 'Folder\/hash.jpg'
            # The imageUrl = 'Folder\/hash.jpg' pattern in inline scripts
            # old_ref is like "Team/hash.jpg", JS has "Team\/hash.jpg"
            old_js = old_ref.replace('/', '\\/')
            new_js = new_ref.replace('/', '\\/')
            c = content.count(old_js)
            if c:
                content = content.replace(old_js, new_js)
                changes += c

        if content != original_content:
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"  Updated {page}.html ({changes} replacements)")
        else:
            print(f"  No changes in {page}.html")


def verify_no_old_paths(mapping):
    print("\nVerifying no old hash paths remain...")
    all_clean = True

    # Collect all hash filenames from the mapping
    hash_names = set()
    for old_ref in mapping.keys():
        fname = os.path.basename(unquote(old_ref))
        hash_names.add(fname)

    for page in PAGES:
        html_path = os.path.join(BASE, f"{page}.html")
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        found = [h for h in hash_names if h in content]
        if found:
            print(f"  FAIL {page}.html: still contains {found[:5]}...")
            all_clean = False
        else:
            print(f"  OK   {page}.html")

    return all_clean


def delete_old_dirs(mapping):
    print("\nDeleting old per-page image directories and root images...")

    dirs_to_delete = [
        'About Us', 'Activities', 'Awards', 'Graduated Students', 'Home',
        'Internship Students', 'Join Us', 'News', 'Projects', 'Publications',
        'Seminars', 'Team', 'Tools'
    ]
    for d in dirs_to_delete:
        path = os.path.join(BASE, d)
        if os.path.isdir(path):
            shutil.rmtree(path)
            print(f"  Deleted dir: {d}/")

    # Delete root-level hash images that were mapped
    for old_ref in mapping.keys():
        if '/' not in old_ref:
            path = os.path.join(BASE, old_ref)
            if os.path.exists(path):
                os.remove(path)
                print(f"  Deleted root: {old_ref}")


if __name__ == '__main__':
    import sys

    step = sys.argv[1] if len(sys.argv) > 1 else 'all'

    print("Step 1: Building mapping...")
    mapping, disk_paths = build_mapping()
    print_mapping(mapping)

    if step == 'mapping-only':
        sys.exit(0)

    print("Step 2: Creating images/ directory...")
    create_images_dir()

    print("Step 3: Copying images...")
    copy_images(mapping, disk_paths)

    print("Step 4: Updating HTML files...")
    update_html_files(mapping)

    print("Step 5: Verification...")
    clean = verify_no_old_paths(mapping)

    if step == 'all' and clean:
        print("\nStep 6: Deleting old directories...")
        delete_old_dirs(mapping)
    elif not clean:
        print("\nSkipping deletion due to verification failure.")

    print("\nDone!")
