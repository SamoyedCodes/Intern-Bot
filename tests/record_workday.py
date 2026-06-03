"""
Playwright Codegen Recorder for Workday Resume Upload Flow.

Usage:
    python3 tests/record_workday.py <workday_job_url>

This opens a browser with the Playwright Inspector recording your actions.
Walk through the resume upload flow manually — the generated Python code
will be printed to stdout when you close the browser.

If no URL is provided, it opens a blank page.
"""
import subprocess
import sys

def main():
    url = sys.argv[1] if len(sys.argv) > 1 else ""
    cmd = [
        sys.executable, "-m", "playwright", "codegen",
        "--target", "python-async",  # generate async Python code
    ]
    if url:
        cmd.append(url)

    print("=" * 60)
    print("PLAYWRIGHT CODEGEN RECORDER")
    print("=" * 60)
    print()
    print("A browser and inspector window will open.")
    print("Manually walk through the Workday application flow:")
    print("  1. Click 'Apply'")
    print("  2. Click 'Autofill with Resume'")
    print("  3. Upload your resume file")
    print("  4. Click 'Save and Continue'")
    print()
    print("The generated code will appear in the inspector panel")
    print("and be printed here when you close the browser.")
    print("=" * 60)
    print()

    subprocess.run(cmd)

if __name__ == "__main__":
    main()
