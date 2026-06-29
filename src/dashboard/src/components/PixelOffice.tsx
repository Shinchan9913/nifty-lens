import { useEffect, useRef } from "react";

/**
 * Top-down 2D pixel office. A <canvas> render loop draws a room seen from above
 * and four characters that WALK AROUND IN 2D (x and y) between zones based on state:
 *   idle      -> sofa / breakroom
 *   thinking  -> own desk (chair)
 *   working   -> own desk (chair)
 *   done      -> own desk (chair)
 *   error     -> bug corner
 *
 * Characters are drawn procedurally (monochrome) so it works with no assets. To use
 * real sprites, use a TOP-DOWN character pack with 4-direction walk rows (e.g. LimeZu
 * "Modern Interiors" character generator — NOT the side-view Platformer set). Drop the
 * PNGs in src/dashboard/public/sprites/ and fill SPRITES[id] below. The canvas is
 * grayscale-filtered (see CSS) so colorful sheets still render monochrome.
 */

type AgentId = "strategist" | "technical" | "risk" | "research";
type Status = "idle" | "working" | "thinking" | "done";
type Dir = "down" | "up" | "left" | "right";

interface SpriteConfig {
  src: string; frameW: number; frameH: number;
  // top-down sheets have one walk row per direction
  rows: { down: number; up: number; left: number; right: number };
  frames: number; fps: number;
  scale?: number; // on-canvas size = frameH * scale (default 1.2)
}
// Sprite sheets + background live in the Python backend at src/agents/sprites/
// and are served by FastAPI at <API_BASE>/agents/sprites/<file>.
// These ship with Ninja Adventure art (pixel-boy, CC0) — cute chibi characters
// normalized to a 4-row (down/up/left/right) x 4-frame walk sheet of 16x16
// cells. A missing/failed image silently falls back to the procedural figure.
const SPRITE_BASE = "http://localhost:8000/agents/sprites";
const BACKGROUND_SRC = `${SPRITE_BASE}/background.png`;
const WALK: Omit<SpriteConfig, "src"> = {
  frameW: 16, frameH: 16,
  rows: { down: 0, up: 1, left: 2, right: 3 },
  frames: 4, fps: 7, scale: 1.25,
};
const SPRITES: Record<AgentId, SpriteConfig | null> = {
  strategist: { src: `${SPRITE_BASE}/strategist.png`, ...WALK },
  technical:  { src: `${SPRITE_BASE}/technical.png`,  ...WALK },
  risk:       { src: `${SPRITE_BASE}/risk.png`,        ...WALK },
  research:   { src: `${SPRITE_BASE}/research.png`,    ...WALK },
};

const W = 340;
const H = 220;
const DPR = 2; // canvas backing-store scale — render at 2x then let CSS downscale for crispness

interface Zone { x: number; y: number; }
const AGENTS: { id: AgentId; name: string; emoji: string; shade: string; desk: Zone; chair: Zone }[] = [
  { id: "strategist", name: "Strategist", emoji: "", shade: "#fafafa", desk: { x: 170, y: 40 }, chair: { x: 170, y: 64 } },
  { id: "technical", name: "Technical", emoji: "", shade: "#d4d4d8", desk: { x: 70, y: 120 }, chair: { x: 70, y: 144 } },
  { id: "risk", name: "Risk", emoji: "", shade: "#a1a1aa", desk: { x: 270, y: 120 }, chair: { x: 270, y: 144 } },
  { id: "research", name: "Research", emoji: "", shade: "#8a8a93", desk: { x: 170, y: 178 }, chair: { x: 170, y: 200 } },
];
const SOFA: Zone = { x: 40, y: 50 };
const BUG: Zone = { x: 300, y: 188 };

interface CharState { x: number; y: number; dir: Dir; t: number; }

export default function PixelOffice({
  statuses, speech, lastMsg, onSelect,
}: {
  statuses: Record<string, Status>;
  speech: Record<string, string>;
  lastMsg: { from: AgentId; to: AgentId; seq: number } | null;
  onSelect: (id: AgentId) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const chars = useRef<Record<string, CharState>>(
    Object.fromEntries(AGENTS.map((a, i) => [a.id, { x: SOFA.x + i * 16, y: SOFA.y + 18, dir: "down" as Dir, t: Math.random() * 9 }]))
  );
  const couriers = useRef<{ from: AgentId; to: AgentId; t: number }[]>([]);
  const statusRef = useRef(statuses);
  statusRef.current = statuses;
  const images = useRef<Record<string, HTMLImageElement | null>>({});
  const bgImg = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    for (const a of AGENTS) {
      const cfg = SPRITES[a.id]; if (!cfg) continue;
      const img = new Image(); img.src = cfg.src;
      img.onload = () => { images.current[a.id] = img; };
      img.onerror = () => { images.current[a.id] = null; };
    }
    const bg = new Image(); bg.src = BACKGROUND_SRC;
    bg.onload = () => { bgImg.current = bg; };
    bg.onerror = () => { bgImg.current = null; };
  }, []);

  useEffect(() => { if (lastMsg) couriers.current.push({ from: lastMsg.from, to: lastMsg.to, t: 0 }); }, [lastMsg]);

  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d")!;
    const host = (canvas.parentElement as HTMLElement) || canvas;

    // Size the canvas to its box in JS so the room ALWAYS fits exactly — no CSS
    // width quirks, no overflow. `scale` maps logical W×H units onto the backing.
    let scale = DPR;
    let lastCw = -1;
    const measure = () => {
      const cw = Math.max(1, host.clientWidth || W);
      if (cw === lastCw) return; // guard against height-feedback resize loops
      lastCw = cw;
      const ch = (cw * H) / W;
      canvas.style.width = `${cw}px`;
      canvas.style.height = `${ch}px`;
      canvas.width = Math.round(cw * DPR);
      canvas.height = Math.round(ch * DPR);
      scale = (cw * DPR) / W;
      ctx.imageSmoothingEnabled = false; // resizing the canvas resets context state
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(host);
    let raf = 0; let prev = performance.now();

    const target = (id: AgentId): Zone => {
      const st = statusRef.current[id] || "idle";
      const a = AGENTS.find((x) => x.id === id)!;
      const idx = AGENTS.findIndex((x) => x.id === id);
      if (st === "idle") return { x: SOFA.x + (idx % 2) * 18, y: SOFA.y + 16 + Math.floor(idx / 2) * 16 };
      return a.chair;
    };

    const draw = (now: number) => {
      const dt = Math.min(0.05, (now - prev) / 1000); prev = now;
      ctx.setTransform(scale, 0, 0, scale, 0, 0); // logical units → backing pixels

      // ---- room (top-down) ----
      if (bgImg.current) {
        // imported floor texture fills the room; a thin frame keeps the wall edge
        ctx.fillStyle = "#0c0c0e"; ctx.fillRect(0, 0, W, H);
        ctx.drawImage(bgImg.current, 8, 8, W - 16, H - 16);
        ctx.fillStyle = "#0c0c0e"; ctx.fillRect(8, 8, W - 16, 6);               // top wall shadow
      } else {
        ctx.fillStyle = "#0c0c0e"; ctx.fillRect(0, 0, W, H);
        ctx.fillStyle = "#17171a"; ctx.fillRect(8, 8, W - 16, H - 16);          // floor
        ctx.fillStyle = "#0c0c0e"; ctx.fillRect(8, 8, W - 16, 6);              // top wall shadow
        // floor tiles
        ctx.fillStyle = "#ffffff06";
        for (let x = 8; x < W - 8; x += 22) ctx.fillRect(x, 8, 1, H - 16);
        for (let y = 8; y < H - 8; y += 22) ctx.fillRect(8, y, W - 16, 1);
      }

      // rugs / zones
      drawRug(ctx, SOFA.x - 4, SOFA.y - 2, 60, 46, "breakroom");
      drawRug(ctx, BUG.x - 26, BUG.y - 18, 52, 40, "bug");
      drawSofa(ctx, SOFA.x - 6, SOFA.y - 10);
      // bug-corner marker
      ctx.fillStyle = "#2a2a2e"; ctx.fillRect(BUG.x - 6, BUG.y - 8, 12, 10);
      ctx.fillStyle = "#e4e4e7"; ctx.font = "6px monospace"; ctx.textBaseline = "top"; ctx.fillText("BUG", BUG.x - 8, BUG.y + 4);

      // desks (top-down)
      for (const a of AGENTS) drawDesk(ctx, a.desk.x, a.desk.y);

      // ---- characters (depth-sorted by y) ----
      const order = [...AGENTS].sort((p, q) => chars.current[p.id].y - chars.current[q.id].y);
      for (const a of order) {
        const c = chars.current[a.id];
        const tg = target(a.id);
        const dx = tg.x - c.x, dy = tg.y - c.y;
        const dist = Math.hypot(dx, dy);
        const moving = dist > 1.5;
        if (moving) {
          const sp = 46 * dt;
          c.x += (dx / dist) * sp; c.y += (dy / dist) * sp;
          c.dir = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "right" : "left") : (dy > 0 ? "down" : "up");
        }
        c.t += dt;
        const st = statusRef.current[a.id] || "idle";
        drawChar(ctx, c, a.shade, a.id, moving, st, images.current[a.id]);
      }

      // ---- couriers (2D) ----
      couriers.current = couriers.current.filter((m) => m.t < 1);
      for (const m of couriers.current) {
        m.t += dt / 0.9;
        const f = chars.current[m.from], t2 = chars.current[m.to];
        if (!f || !t2) continue;  // skip messages to/from anyone without a desk (e.g. the Planner)
        const x = lerp(f.x, t2.x, ease(m.t));
        const y = lerp(f.y, t2.y, ease(m.t)) - Math.sin(m.t * Math.PI) * 16 - 8;
        ctx.fillStyle = "#0c0c0e"; ctx.fillRect(x - 4, y - 3, 8, 6);
        ctx.fillStyle = "#e4e4e7"; ctx.fillRect(x - 3, y - 2, 6, 4);
        ctx.fillStyle = "#0c0c0e"; ctx.fillRect(x - 3, y - 2, 6, 1);
      }

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, []);

  return (
    <div className="px-office">
      <canvas ref={canvasRef} className="px-canvas" />
      <div className="px-overlay">
        <div className="px-tag">Market Analysis Floor</div>
        {AGENTS.map((a) => (
          <div key={a.id} className="px-plate" style={{ left: `${(a.desk.x / W) * 100}%`, top: `${(a.desk.y / H) * 100 - 13}%` }}
            onClick={() => onSelect(a.id)} title="Click for full transcript">
            {speech[a.id] && <div className="px-speech">{speech[a.id]}…</div>}
            <span className="px-name">{a.name}</span>
            <span className={`px-status s-${statuses[a.id] || "idle"}`}>{statuses[a.id] || "idle"}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------- drawing ----------------
function drawChar(ctx: CanvasRenderingContext2D, c: CharState, shade: string, id: string, moving: boolean, st: Status, img: HTMLImageElement | null | undefined) {
  const cfg = SPRITES[id as AgentId];
  const x = Math.round(c.x), y = Math.round(c.y);
  if (cfg && img) {
    const row = cfg.rows[c.dir];
    const frame = moving ? Math.floor(c.t * cfg.fps) % cfg.frames : 0;
    const sc = cfg.scale ?? 1.2, dw = cfg.frameW * sc, dh = cfg.frameH * sc;
    ctx.fillStyle = "#00000055"; ctx.fillRect(x - 5, y + 1, 10, 3); // ground shadow
    ctx.drawImage(img, frame * cfg.frameW, row * cfg.frameH, cfg.frameW, cfg.frameH, x - dw / 2, y - dh + 4, dw, dh);
    return;
  }
  // procedural top-down monochrome figure
  const step = moving ? (Math.floor(c.t * 9) % 2 === 0 ? 1 : -1) : 0;
  const bob = moving ? 0 : (st === "idle" ? Math.sin(c.t * 3) * 0.6 : Math.sin(c.t * 6) * 0.4);
  const yy = y + bob;
  const O = "#0c0c0e";
  // shadow
  ctx.fillStyle = "#00000055"; ctx.fillRect(x - 6, y + 1, 12, 3);
  // feet (alternate when walking)
  ctx.fillStyle = "#3f3f46";
  ctx.fillRect(x - 4, yy - 2 + step, 3, 3);
  ctx.fillRect(x + 1, yy - 2 - step, 3, 3);
  // body (top-down torso)
  ctx.fillStyle = O; ctx.fillRect(x - 6, yy - 12, 12, 11);
  ctx.fillStyle = shade; ctx.fillRect(x - 5, yy - 11, 10, 9);
  // head (seen slightly from above)
  ctx.fillStyle = O; ctx.fillRect(x - 4, yy - 17, 8, 7);
  ctx.fillStyle = shade; ctx.fillRect(x - 3, yy - 16, 6, 5);
  // facing indicator (a darker "face" pixel toward dir)
  ctx.fillStyle = O;
  const fx = c.dir === "left" ? x - 3 : c.dir === "right" ? x + 1 : x - 1;
  const fy = c.dir === "up" ? yy - 16 : yy - 13;
  ctx.fillRect(fx, fy, 2, 2);
  // status glyph
  if (st === "thinking") { ctx.fillStyle = "#fafafa"; const d = Math.floor(c.t * 3) % 3; for (let i = 0; i <= d; i++) ctx.fillRect(x - 3 + i * 3, yy - 22, 2, 2); }
  else if (st === "working") { ctx.fillStyle = "#fafafa"; ctx.fillRect(x - 1, yy - 22, 2, 4); }
  else if (st === "done") { ctx.fillStyle = "#d4d4d8"; ctx.fillRect(x - 2, yy - 20, 1, 2); ctx.fillRect(x - 1, yy - 19, 1, 2); ctx.fillRect(x, yy - 21, 1, 3); }
}

function drawDesk(ctx: CanvasRenderingContext2D, x: number, y: number) {
  ctx.fillStyle = "#26262b"; ctx.fillRect(x - 18, y - 8, 36, 16);     // desktop (top-down)
  ctx.fillStyle = "#1a1a1d"; ctx.fillRect(x - 18, y - 8, 36, 2);
  ctx.fillStyle = "#0e0e10"; ctx.fillRect(x - 10, y - 5, 20, 8);      // screen seen from above
  ctx.fillStyle = "#52525b"; ctx.fillRect(x - 9, y - 4, 18, 2);
}

function drawSofa(ctx: CanvasRenderingContext2D, x: number, y: number) {
  ctx.fillStyle = "#2a2a2e"; ctx.fillRect(x, y, 40, 22);
  ctx.fillStyle = "#34343a"; ctx.fillRect(x, y, 40, 6);
  ctx.fillStyle = "#1f1f23"; ctx.fillRect(x + 3, y + 8, 34, 11);
}

function drawRug(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, _k: string) {
  ctx.fillStyle = "#ffffff05"; ctx.fillRect(x, y, w, h);
  ctx.fillStyle = "#ffffff10"; ctx.fillRect(x, y, w, 1); ctx.fillRect(x, y + h - 1, w, 1);
}

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const ease = (t: number) => (t < 0 ? 0 : t > 1 ? 1 : t * t * (3 - 2 * t));
