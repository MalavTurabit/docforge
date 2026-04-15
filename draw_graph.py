# Run this as a standalone script in your project root
from dotenv import load_dotenv
load_dotenv()

from app.graph.graph import citerag_graph

# Draw and save as PNG
png_bytes = citerag_graph.get_graph().draw_mermaid_png()

with open("citerag_graph.png", "wb") as f:
    f.write(png_bytes)

print("Saved: citerag_graph.png")