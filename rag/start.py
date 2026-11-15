"""Entry point. Maritime injects PORT; locally it defaults to 8100."""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("rag.agent:app", host="0.0.0.0", port=int(os.getenv("PORT", "8100")))
