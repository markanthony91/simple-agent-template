const { Client } = require("pg");
(async () => {
  const db = new Client({ connectionString: process.env.DATABASE_URL });
  await db.connect();
  try {
    await db.query("BEGIN READ ONLY");
    await db.query("SET LOCAL statement_timeout = '5s'");
    const query = async (sql) => (await db.query(sql)).rows;
    const prefix =
      "FROM zerai_gateway.inbound_messages i JOIN zerai_gateway.conversations c ON i.conversation_id=c.id WHERE c.scope_id=7 AND c.channel='whatsapp' AND c.runtime_target='homologation'";
    const out = {
      at: new Date().toISOString(),
      route: await query(
        "SELECT runtime_target,active,count(*)::int n FROM zerai_gateway.routes WHERE scope_id=7 GROUP BY 1,2",
      ),
      bindings: await query(
        "SELECT count(*)::int AS conversations FROM zerai_gateway.conversations WHERE scope_id=7 AND channel='whatsapp' AND runtime_target='homologation'",
      ),
      counts: await query(
        "SELECT i.status,count(*)::int AS rows, count(*) FILTER (WHERE i.created_at>=now()-interval '24 hours')::int AS last24h,min(i.created_at) first_seen,max(i.created_at) last_seen " +
          prefix +
          " GROUP BY 1",
      ),
      latency7d: await query(
        "SELECT count(*)::int AS accepted, percentile_cont(ARRAY[0.5,0.95]) WITHIN GROUP (ORDER BY extract(epoch from i.updated_at-i.created_at)) AS ingress_to_accepted_seconds " +
          prefix +
          " AND i.status='accepted' AND i.created_at >=now()-interval '7 days'",
      ),
      worker_enabled: process.env.GATEWAY_WORKER_ENABLED === "true",
      source_sha256: Object.fromEntries(
        ["main", "worker", "transport"].map((name) => [
          name,
          require("node:crypto")
            .createHash("sha256")
            .update(
              require("node:fs").readFileSync(
                process.cwd() + "/src/" + name + ".js",
              ),
            )
            .digest("hex"),
        ]),
      ),
      version: require(process.cwd() + "/package.json").version,
    };
    console.log("SAFE " + JSON.stringify(out));
  } finally {
    await db.end();
  }
})().catch((e) => {
  console.error("safe_error " + (e.code || e.name));
  process.exitCode = 1;
});
