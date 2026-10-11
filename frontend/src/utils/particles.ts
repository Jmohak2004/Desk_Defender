// Lightweight particle system for the battlefield canvas.

export interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  max: number;
  color: string;
  size: number;
  kind: 'spark' | 'ring' | 'text' | 'debris' | 'flash';
  text?: string;
  radius?: number;
}

export class ParticleSystem {
  items: Particle[] = [];
  shake = 0;

  burst(x: number, y: number, color: string, count: number, speed = 160, size = 3, life = 0.6) {
    for (let i = 0; i < count; i++) {
      const a = Math.random() * Math.PI * 2;
      const s = speed * (0.35 + Math.random() * 0.65);
      this.items.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s, life, max: life, color, size: size * (0.6 + Math.random() * 0.8), kind: 'spark' });
    }
  }

  debris(x: number, y: number, color: string, count = 14) {
    for (let i = 0; i < count; i++) {
      const a = Math.random() * Math.PI * 2;
      const s = 60 + Math.random() * 140;
      this.items.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s - 40, life: 1.1, max: 1.1, color, size: 3 + Math.random() * 5, kind: 'debris' });
    }
  }

  ring(x: number, y: number, color: string, radius: number, life = 0.6) {
    this.items.push({ x, y, vx: 0, vy: 0, life, max: life, color, size: 3, kind: 'ring', radius });
  }

  flash(x: number, y: number, color: string, radius: number) {
    this.items.push({ x, y, vx: 0, vy: 0, life: 0.25, max: 0.25, color, size: 1, kind: 'flash', radius });
  }

  text(x: number, y: number, text: string, color: string) {
    this.items.push({ x, y, vx: 0, vy: -45, life: 1.0, max: 1.0, color, size: 15, kind: 'text', text });
  }

  update(dt: number) {
    this.shake = Math.max(0, this.shake - dt * 30);
    const next: Particle[] = [];
    for (const p of this.items) {
      p.life -= dt;
      if (p.life <= 0) continue;
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      if (p.kind === 'spark') {
        p.vx *= 0.9;
        p.vy *= 0.9;
      } else if (p.kind === 'debris') {
        p.vy += 260 * dt;
        p.vx *= 0.97;
      }
      next.push(p);
    }
    this.items = next.length > 1500 ? next.slice(-1500) : next;
  }

  draw(ctx: CanvasRenderingContext2D) {
    for (const p of this.items) {
      const t = p.life / p.max;
      ctx.globalAlpha = Math.max(0, t);
      if (p.kind === 'ring') {
        ctx.strokeStyle = p.color;
        ctx.lineWidth = 3 * t + 1;
        ctx.beginPath();
        ctx.arc(p.x, p.y, (p.radius ?? 40) * (1 - t * 0.85), 0, Math.PI * 2);
        ctx.stroke();
      } else if (p.kind === 'flash') {
        const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.radius ?? 60);
        g.addColorStop(0, p.color);
        g.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius ?? 60, 0, Math.PI * 2);
        ctx.fill();
      } else if (p.kind === 'text') {
        ctx.fillStyle = p.color;
        ctx.font = `700 ${p.size}px "JetBrains Mono", monospace`;
        ctx.textAlign = 'center';
        ctx.fillText(p.text ?? '', p.x, p.y);
      } else {
        ctx.fillStyle = p.color;
        ctx.fillRect(p.x - p.size / 2, p.y - p.size / 2, p.size, p.size);
      }
    }
    ctx.globalAlpha = 1;
  }
}
