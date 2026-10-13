// 공개 페이지의 '조회 요청'을 받아 GitHub 의 docs/request.json 에 기록하는 Cloudflare Worker.
// 토큰(GITHUB_TOKEN)은 Worker 비밀값에만 있고 페이지·저장소에는 없다.
// 이 PC 는 요청을 직접 받지 않고, 스케줄러가 request.json 을 가져가 조회한다 (poll_request.py).
//
// 환경 변수 (wrangler.toml [vars] / secret):
//   GITHUB_TOKEN  (secret)  이 저장소 Contents 읽기/쓰기만 가진 fine-grained 토큰
//   REPO          예: cnrudals123456789-gicorp/view_searching_20261013
//   ALLOWED_ORIGIN 예: https://cnrudals123456789-gicorp.github.io
//   COOLDOWN_MIN  기본 30 (마지막 조회 완료 후 이 시간 안에는 거절)
//   DAILY_CAP     기본 12 (하루 최대 요청 수, KST 기준)

const FILE = "docs/request.json";
const STALE_MIN = 90;

function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...cors },
  });
}

function b64encode(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

function b64decode(b64) {
  const bin = atob(b64.replace(/\n/g, ""));
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

const minutesSince = (iso) => (iso ? (Date.now() - Date.parse(iso)) / 60000 : null);
const kstDay = () => new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);

export default {
  async fetch(request, env) {
    const cors = {
      "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN,
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      Vary: "Origin",
    };
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });

    const url = new URL(request.url);
    if (request.method !== "POST" || url.pathname !== "/request") return json({ ok: false, msg: "not found" }, 404, cors);
    if ((request.headers.get("Origin") || "") !== env.ALLOWED_ORIGIN) return json({ ok: false, msg: "허용되지 않은 요청입니다." }, 403, cors);

    const cooldown = Number(env.COOLDOWN_MIN || 30);
    const cap = Number(env.DAILY_CAP || 12);
    const api = `https://api.github.com/repos/${env.REPO}/contents/${FILE}`;
    const headers = {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "User-Agent": "view-rank-worker",
      Accept: "application/vnd.github+json",
    };

    const cur = await fetch(`${api}?ref=main`, { headers });
    if (!cur.ok) return json({ ok: false, msg: "상태 파일을 읽지 못했습니다." }, 502, cors);
    const meta = await cur.json();
    let req = {};
    try { req = JSON.parse(b64decode(meta.content)); } catch (e) { /* 비어 있으면 새로 시작 */ }

    // 1) 이미 요청/조회 중
    if ((req.status === "pending" || req.status === "running")) {
      const since = minutesSince(req.status === "running" ? req.started_at : req.requested_at);
      if (since === null || since < STALE_MIN) {
        return json({ ok: false, msg: req.status === "running" ? "지금 조회가 진행 중입니다." : "이미 조회 요청이 접수되어 PC 응답을 기다리는 중입니다.", status: req.status }, 409, cors);
      }
    }
    // 2) 쿨다운
    const last = minutesSince(req.last_run_at);
    if (last !== null && last < cooldown) {
      const wait = Math.ceil(cooldown - last);
      return json({ ok: false, msg: `최근에 조회했습니다. ${wait}분 뒤에 다시 요청할 수 있습니다.`, wait_min: wait }, 429, cors);
    }
    // 3) 하루 상한
    const day = kstDay();
    const count = req.day === day ? Number(req.count || 0) : 0;
    if (count >= cap) return json({ ok: false, msg: "오늘 조회 요청 한도에 도달했습니다. 내일 다시 요청해 주세요." }, 429, cors);

    const next = {
      ...req,
      id: crypto.randomUUID(),
      status: "pending",
      requested_at: new Date().toISOString(),
      started_at: null,
      finished_at: null,
      message: "PC 응답 대기 중",
      day,
      count: count + 1,
    };
    const put = await fetch(api, {
      method: "PUT",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "조회 요청 (공개 페이지)",
        content: b64encode(JSON.stringify(next, null, 2) + "\n"),
        sha: meta.sha,
        branch: "main",
      }),
    });
    if (put.status === 409 || put.status === 422) return json({ ok: false, msg: "다른 요청이 동시에 처리되었습니다. 잠시 후 다시 시도해 주세요." }, 409, cors);
    if (!put.ok) return json({ ok: false, msg: "요청을 기록하지 못했습니다." }, 502, cors);
    return json({ ok: true, msg: "조회 요청이 접수되었습니다. 이 PC가 켜져 있으면 보통 10~15분 안에 반영됩니다.", id: next.id }, 200, cors);
  },
};
