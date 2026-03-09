import os
import random
from datetime import timedelta
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from azure.monitor.query import LogsQueryClient, LogsQueryStatus
from azure.identity import DefaultAzureCredential
import uvicorn

app = FastAPI()

credential = DefaultAzureCredential()
client = LogsQueryClient(credential)
WORKSPACE_ID = os.environ.get("LOG_ANALYTICS_WORKSPACE_ID")

TIMEFRAME_MAP = {
    "PT1H": timedelta(hours=1),
    "PT24H": timedelta(days=1),
    "P7D": timedelta(days=7)
}

@app.get("/api/GetLogs")
async def get_logs(timespan: str = "PT24H"):
    if not WORKSPACE_ID:
        return {"error": "Falta la variable de entorno LOG_ANALYTICS_WORKSPACE_ID"}

    t_delta = TIMEFRAME_MAP.get(timespan, timedelta(days=1))

    # QUERY RESILIENTE: Foco en Inbound para exactitud sin pérdida de datos
    query = (
        'ContainerLog '
        '| where TimeGenerated > ago(24h) '
        '| where LogEntry has_any ("alm-inbound-smart", "alm-inbound-smart-la") '
        '| where LogEntry has "HTTP/1.1\\"" ' # Filtramos solo logs de acceso (más fiables)
        '| extend Status = toint(extract("HTTP/1\\\\.1\\" (\\\\d+)", 1, LogEntry)), '
        '         Latency = todouble(extract(" (\\\\d+\\\\.\\\\d+) \\\\[", 1, LogEntry)), '
        '         Country = extract("/country/([^/]+)/", 1, LogEntry) '
        '| where isnotempty(Country) '
        '| summarize '
        '    Total = count(), '
        '    OK = countif(Status < 400), '
        '    Error500 = countif(Status >= 500), '
        '    Error400 = countif(Status >= 400 and Status < 500), '
        '    AvgLatency = avg(Latency) * 1000 '
        '  by system = "Smart", country_code = toupper(Country)'
    )

    try:
        response = client.query_workspace(workspace_id=WORKSPACE_ID, query=query, timespan=t_delta)
        results = []
        if response.status == LogsQueryStatus.SUCCESS:
            data = response.tables[0]
            country_names = {"ES": "España", "PT": "Portugal", "CO": "Colombia", "AR": "Argentina", "PE": "Perú", "UY": "Uruguay", "PY": "Paraguay", "CL": "Chile"}
            
            for row in data.rows:
                c_code = str(row[1])
                tx = int(row[2])
                results.append({
                    "country_code": c_code,
                    "country_name": country_names.get(c_code, c_code),
                    "system": str(row[0]),
                    "transactions": tx,
                    "expected_transactions": int(tx * 1.1), 
                    "avg_latency": round(float(row[6] or 0), 2),
                    "history": [random.randint(int(tx*0.7), tx) for _ in range(12)],
                    "stats": {
                        "200 OK": int(row[3]),
                        "500 Server Error": int(row[4]),
                        "400 Bad Request": int(row[5])
                    }
                })
        return results
    except Exception as e:
        return {"error": str(e)}

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return {"error": "index.html no encontrado"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
