# Google Doc Targets Demo

This demo shows how to use Google Docs as manuscript sources with markmeld.

## Setup

1. **Set up Google Drive credentials:**
   ```bash
   export MM_GOOGLE_DRIVE_CREDENTIALS="/path/to/service-account-key.json"
   # OR
   export MM_GOOGLE_DRIVE_CREDENTIALS='{"type": "service_account", ...}'  # JSON content
   ```

2. **Get your Google Doc ID:**
   - Open your Google Doc
   - The ID is in the URL: `https://docs.google.com/document/d/YOUR_DOC_ID_HERE/edit`

3. **Optional: Get folder ID for figures:**
   - If your figures are in a Google Drive folder
   - Open the folder and get the ID from the URL

## Usage

1. Edit `_markmeld.yaml` to add your Google Doc ID:
   ```yaml
   targets:
     my_doc:
       type: google-doc
       jinja_template: template.jinja
       output_file: output.pdf
       data:
         google_docs:
           doc_id: "YOUR_GOOGLE_DOC_ID"
           folder_id: "OPTIONAL_FOLDER_ID"  # If you have figures
   ```

2. Build the target:
   ```bash
   mm my_doc
   ```

## How It Works

1. **Fetching:** The Google Doc is downloaded as markdown (with automatic caching)
2. **Figure Processing:** If a folder_id is provided:
   - SVG files are converted to PDF
   - CSV files are downloaded
   - All files are cached locally
3. **Path Updates:** Figure paths in the document are updated to point to cached/converted versions
4. **Normal Processing:** After preprocessing, the target continues as a normal markmeld target

## Benefits

- **Cloud-native:** Work directly with Google Docs without manual exports
- **Automatic caching:** Documents and figures are cached for fast rebuilds
- **Figure conversion:** SVG→PDF conversion happens automatically
- **Seamless integration:** After preprocessing, works exactly like local content

## Cache Location

Cached content is stored in `.cache/` directory:
```
.cache/
├── {doc_id}/
│   ├── docs/          # Cached markdown documents
│   ├── converted/     # Converted figures (SVG→PDF)
│   └── csv/           # Downloaded CSV files
```

## Troubleshooting

- **Authentication errors:** Check that your service account has access to the document
- **Missing figures:** Ensure the folder_id is correct and accessible
- **Cache issues:** Delete `.cache/` directory to force fresh download