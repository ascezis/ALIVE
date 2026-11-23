"""Run the local ALIVE app on the loopback interface."""

import os

import uvicorn


if __name__ == "__main__":
    os.environ["ALIVE_LOCAL_DEV"] = "1"
    port = int(os.environ.get("ALIVE_API_PORT", "4174"))
    uvicorn.run("backend.app:app", host="127.0.0.1", port=port, proxy_headers=False, access_log=False)
