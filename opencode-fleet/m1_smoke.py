"""M1 smoke: OpencodeSpawner launch -> alive -> exit -> session-id capture."""
import sys, time
sys.path.insert(0, r"C:\Projects\Learning\eda-base3\edp-pool\src")
from edp_pool.opencode_launcher import OpencodeSpawner

sp = OpencodeSpawner(log_dir=r"C:\Projects\Learning\eda-base3\opencode-fleet\.fleet-logs",
                     broker_url="http://127.0.0.1:9300",
                     pool_url="http://127.0.0.1:9301",
                     agent_home=r"C:\Projects\Learning\eda-base3\claude")
sid = f"m1-smoke-{int(time.time())}"
sp.launch(sid, "worker", "m1-plan:a1",
          activation="M1 smoke turn: do not use tools. Reply with exactly: M1-READY")
print("launched, alive:", sp.alive(sid), "pid:", sp.pid(sid))
for _ in range(120):
    if not sp.alive(sid):
        break
    time.sleep(2)
print("exited, alive now:", sp.alive(sid), "knows:", sp.knows(sid))
print("captured opencode session:", sp.opencode_session_id(sid))
log = sp._launches[sid].log_path
tail = open(log, "rb").read().decode("utf-8", "replace")
print("log tail:", tail[-300:].strip()[-200:])
