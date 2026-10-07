.PHONY: test web api
test: ; pytest -q
web:  ; adk web agents          # ADK dev UI at http://localhost:8000
api:  ; ADK_WEB=false python server.py
