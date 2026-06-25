import os

from dotenv import load_dotenv
from llama_cloud import LlamaCloud

load_dotenv()

llama_cloud_api_key = os.getenv("LLAMA_CLOUD_API_KEY")

client = LlamaCloud(api_key=llama_cloud_api_key)
# Upload and parse a document
# file = client.files.create(file="./TSLA-Q1-2026-Update-simple.pdf", purpose="parse")
# ./TSLA-Q1-2026-Update-simple.pdf: 27f8bf52-5242-42fd-b78a-9b11b2552786
# print("file id:", file.id)
fileId = "27f8bf52-5242-42fd-b78a-9b11b2552786"

result = client.parsing.parse(
    file_id=fileId,
    tier="agentic",
    version="latest",
    input_options={
        # "target_pages": "0-50",
    },
    output_options={
        "markdown": {
            "tables": {"output_tables_as_markdown": True},
        },
        "images_to_save": ["screenshot"],
    },
    processing_options={
        "ocr_parameters": {"languages": ["en"]},
    },
    expand=["text", "markdown", "items", "images_content_metadata"],
)

# Print the markdown for the first page
print(result.markdown.pages[0].markdown)

# Save into a local markdown file
all_markdown = []
for page in result.markdown.pages:
    all_markdown.append(page.markdown)

full_text = "\n\n".join(all_markdown)

with open("TSLA_Q1_2026-Update-simple-parse-options.md", "w", encoding="utf-8") as f:
    for i, page in enumerate(result.markdown.pages):
        f.write(f"<!-- Page {i + 1} -->\n")
        f.write(page.markdown)
        f.write("\n\n---\n\n")

print(f"✅ Save successed，total {len(result.markdown.pages)} pages")
