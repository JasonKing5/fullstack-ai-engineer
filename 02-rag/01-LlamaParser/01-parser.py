import os

from dotenv import load_dotenv
from llama_cloud import LlamaCloud

load_dotenv()

llama_cloud_api_key = os.getenv("LLAMA_CLOUD_API_KEY")

client = LlamaCloud(api_key=llama_cloud_api_key)
# Upload and parse a document
file = client.files.create(file="./TSLA-Q1-2026-Update-simple.pdf", purpose="parse")
# ./TSLA-Q1-2026-Update-simple.pdf: 27f8bf52-5242-42fd-b78a-9b11b2552786
print("file id:", file.id)

result = client.parsing.parse(
    file_id=file.id,
    tier="agentic",
    version="latest",
    expand=["markdown"],
)

# Print the markdown for the first page
print(result.markdown.pages[0].markdown)
