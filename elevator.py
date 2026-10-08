#!/usr/bin/env python3
"""
ELEVATOR MUSIC GENERATOR — лифтовая музыка из чистой математики.
Никаких нейросетей и сэмплов: FM-синтез, босса-ритмы и джазовые аккорды пишутся кодом.

Запуск:   python3 elevator.py                 → 5 треков по 45 секунд в папку elevator_music/
          python3 elevator.py -n 3 -s 60      → 3 трека по минуте
          python3 elevator.py --style bossa   → только босса (bossa, lobby, mall80s, swing, spa)
          python3 elevator.py --seed 42       → повторить подборку (зерно трека — в имени файла)
Нужен только numpy:  pip install numpy

Сделано агентом для CTRL+PLAY · ctrlxplay.ru
"""
import argparse, os, random, wave
import numpy as np

SR = 44100
def hz(m): return 440.0 * 2 ** ((m - 69) / 12)

# ───────────────────────── инструменты ─────────────────────────
def adsr(n, a, d, s, r, hold):
    t = np.arange(n) / SR; e = np.full(n, s, float)
    e[t < a] = t[t < a] / max(a, 1e-4)
    m = (t >= a) & (t < a + d); e[m] = 1 - (1 - s) * (t[m] - a) / d
    tail = t > hold; e[tail] *= np.exp(-(t[tail] - hold) / r)
    return e

def fm_rhodes(f, length, vel, bright=1.0):          # 2-операторный FM, как E.PIANO на DX7
    n = int((length + 0.9) * SR); t = np.arange(n) / SR
    idx = bright * (1.7 * np.exp(-t * 3.2) + 0.25)
    tine = 0.4 * bright * np.exp(-t * 14) * np.sin(2 * np.pi * f * 14 * t)
    s = np.sin(2 * np.pi * f * t + idx * np.sin(2 * np.pi * f * t) + tine)
    return s * adsr(n, 0.003, 1.0, 0.3, 0.3, length) * (1 + 0.1 * np.sin(2 * np.pi * 4.6 * t)) * vel

def fm_pad(f, length, vel):                          # мягкий пэд: медленная атака, лёгкая расстройка
    n = int((length + 1.5) * SR); t = np.arange(n) / SR
    s = sum(np.sin(2 * np.pi * f * d * t + 0.6 * np.sin(2 * np.pi * f * 2 * t)) for d in (0.997, 1.0, 1.004)) / 3
    return s * adsr(n, 0.6, 0.5, 0.8, 0.8, length) * vel

def vibes(f, length, vel):                           # виброфон с мотором
    n = int((length + 1.4) * SR); t = np.arange(n) / SR
    s = np.sin(2 * np.pi * f * t) + 0.22 * np.sin(2 * np.pi * f * 4 * t) * np.exp(-t * 7)
    return s * np.exp(-t * 1.5) * (1 + 0.35 * np.sin(2 * np.pi * 5.5 * t)) * vel

def bell(f, length, vel):                            # колокольчик/арфа для spa
    n = int((length + 2.0) * SR); t = np.arange(n) / SR
    s = np.sin(2 * np.pi * f * t + 1.2 * np.exp(-t * 2) * np.sin(2 * np.pi * f * 3.5 * t))
    return s * np.exp(-t * 1.1) * vel

def upright(f, length, vel):                         # контрабас
    n = int((length + 0.15) * SR); t = np.arange(n) / SR
    s = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) + 0.1 * np.sin(6 * np.pi * f * t)
    return s * adsr(n, 0.008, 0.3, 0.55, 0.07, length) * vel

def synth_bass(f, length, vel):                      # 80-е: FM-бас
    n = int((length + 0.08) * SR); t = np.arange(n) / SR
    s = np.sin(2 * np.pi * f * t + 2.2 * np.exp(-t * 9) * np.sin(2 * np.pi * f * t))
    return s * adsr(n, 0.002, 0.15, 0.5, 0.04, length) * vel

def noise_hit(length, decay, hp=True, vel=1.0):
    n = int(length * SR); x = np.random.randn(n)
    if hp: x = np.diff(np.r_[0.0, x])
    return x * np.exp(-np.arange(n) / SR * decay) * vel

def rim(vel):
    n = int(0.07 * SR); t = np.arange(n) / SR
    return (np.sin(2 * np.pi * 1700 * t) * 0.7 + np.random.randn(n) * 0.3) * np.exp(-t * 90) * vel

def kick(vel):
    n = int(0.3 * SR); t = np.arange(n) / SR
    return np.sin(2 * np.pi * (48 + 90 * np.exp(-t * 30)) * t) * np.exp(-t * 9) * vel

def ride(vel):
    n = int(0.6 * SR); t = np.arange(n) / SR
    s = sum(np.sin(2 * np.pi * f * t) for f in (3150, 4370, 5210, 6830)) / 4 + 0.4 * np.random.randn(n)
    return np.diff(np.r_[0.0, s]) * np.exp(-t * 6) * vel

# ───────────────────────── гармония ─────────────────────────
# аккорды: (бас, [голоса]) относительно C; транспонируем в случайную тональность
PROGS = {
    "ii-V-I-VI":  [(2, [5, 9, 12, 16]), (7, [5, 9, 11, 16]), (0, [4, 7, 11, 14]), (9, [7, 10, 13, 16])],
    "I-vi-ii-V":  [(0, [4, 7, 11, 14]), (9, [7, 12, 16, 19]), (2, [5, 9, 12, 16]), (7, [5, 9, 11, 16])],
    "IV-iii-ii-I": [(5, [9, 12, 16, 19]), (4, [7, 11, 14, 19]), (2, [5, 9, 12, 16]), (0, [4, 7, 11, 14])],
    "I-IV vamp":  [(0, [4, 7, 11, 14]), (0, [4, 7, 11, 14]), (5, [9, 12, 16, 19]), (5, [9, 12, 16, 19])],
}
STYLES = {
    "bossa":   dict(bpm=(78, 92),  progs=["ii-V-I-VI", "I-vi-ii-V"], swing=0.0),
    "lobby":   dict(bpm=(64, 74),  progs=["IV-iii-ii-I", "I-IV vamp"], swing=0.0),
    "mall80s": dict(bpm=(96, 108), progs=["I-vi-ii-V", "IV-iii-ii-I"], swing=0.0),
    "swing":   dict(bpm=(112, 128), progs=["ii-V-I-VI", "I-vi-ii-V"], swing=0.62),
    "spa":     dict(bpm=(56, 64),  progs=["I-IV vamp", "IV-iii-ii-I"], swing=0.0),
}
KEYS = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

def melody(rng, prog, bars, base):
    """Мелодия: случайное блуждание по тонам аккорда с проходящими нотами, фразы по 2 такта."""
    notes, cur = [], base + 16
    for b in range(bars):
        ch = [base + 12 + v for v in prog[b % 4][1]]
        pool = sorted(set(ch + [c + 12 for c in ch]))
        beat = 0.0
        rhythm = rng.choice([[1.5, 0.5, 2], [1, 1, 1, 1], [2, 1, 1], [0.5, 1, 0.5, 2], [3, 1]])
        if b % 2 == 1 and rng.random() < 0.5: rhythm = [2, 2]   # вздох в конце фразы
        for ln in rhythm:
            cand = [p for p in pool if abs(p - cur) <= 5] or pool
            cur = rng.choice(cand)
            if b % 2 == 1 and ln >= 2 and rng.random() < 0.6: cur = rng.choice([p for p in pool if p % 12 == ch[0] % 12] or [cur])
            notes.append((b, beat, cur, ln)); beat += ln
    return notes

# ───────────────────────── трек ─────────────────────────
def render(style, seconds, seed):
    rng = random.Random(seed); np.random.seed(seed % (2**32))
    st = STYLES[style]; bpm = rng.uniform(*st["bpm"]); key = rng.randrange(12)
    prog_name = rng.choice(st["progs"]); prog = PROGS[prog_name]
    beat = 60 / bpm; bar = 4 * beat
    bars = max(8, int(round(seconds / bar / 4)) * 4); N = int(round(bars * bar * SR))
    L = np.zeros(N); R = np.zeros(N)

    def put(sig, t, pan=0.0, g=1.0):
        i = int(t * SR) % N; n = min(len(sig), N)
        gl, gr = g * np.sqrt((1 - pan) / 2), g * np.sqrt((1 + pan) / 2)
        for buf, gg in ((L, gl), (R, gr)):
            k = min(n, N - i); buf[i:i + k] += sig[:k] * gg
            if n > k: buf[:n - k] += sig[k:n] * gg        # хвост заворачиваем в начало — бесшовный луп

    def sw(pos):                                          # свинг: восьмые «и» оттягиваются
        whole, frac = divmod(pos, 1.0)
        return whole + (st["swing"] if st["swing"] and abs(frac - 0.5) < 1e-6 else frac)

    base = 48 + key if key < 6 else 36 + key
    hum = lambda: rng.uniform(-0.008, 0.008)
    mel = melody(rng, prog, bars, base)
    for b in range(bars):
        t0 = b * bar; root, voices = prog[b % 4]
        chord = [hz(base + 12 + v) for v in voices]; broot = hz(base - 12 + root)
        if style == "bossa":
            for c in [0, 1.5, 2.5, 3.5] if b % 2 == 0 else [0.5, 1.5, 3]:
                for k, f in enumerate(chord): put(fm_rhodes(f, beat * 0.8, 0.2), t0 + c * beat + k * 0.007 + hum(), -0.35 + 0.2 * k)
            for c, iv in [(0, 0), (1.5, 7), (2, 7), (3.5, 0)]: put(upright(broot * 2 ** (iv / 12), beat * 0.9, 0.55), t0 + c * beat)
            for e in range(8): put(noise_hit(0.08, 50, vel=0.10 if e % 2 else 0.06), t0 + e * beat / 2 + hum(), 0.5)
            for c in ([0, 1.5, 3] if b % 2 == 0 else [1, 2.5]): put(rim(0.3), t0 + c * beat, -0.4)
            lead = vibes
        elif style == "lobby":
            for k, f in enumerate(chord): put(fm_pad(f, bar * 0.98, 0.16), t0 + k * 0.02, -0.5 + 0.33 * k)
            for c in [0, 2]: put(upright(broot * (1.5 if c else 1), beat * 1.8, 0.5), t0 + c * beat)
            for c in range(4): put(noise_hit(0.35, 7, vel=0.05), t0 + c * beat + hum(), 0.3)   # щётки
            lead = vibes
        elif style == "mall80s":
            for c in [0, 0.75, 1.5, 2.5, 3.25]:
                for k, f in enumerate(chord): put(fm_rhodes(f, beat * 0.5, 0.17, bright=1.6), t0 + c * beat + k * 0.004, -0.3 + 0.2 * k)
            for e in range(8): put(synth_bass(broot * (2 if e % 4 == 3 else 1), beat * 0.4, 0.5), t0 + e * beat / 2)
            for c in [0, 2]: put(kick(0.7), t0 + c * beat)
            for c in [1, 3]: put(noise_hit(0.25, 14, hp=False, vel=0.25), t0 + c * beat, 0.1)       # клэп
            for e in range(8): put(noise_hit(0.05, 70, vel=0.07), t0 + e * beat / 2, 0.45)
            lead = fm_rhodes
        elif style == "swing":
            for c in [0, 1.5] if b % 2 == 0 else [0.5, 2.5]:                                       # чарльстон
                for k, f in enumerate(chord): put(fm_rhodes(f, beat * 0.6, 0.18), t0 + sw(c) * beat + k * 0.006, -0.3 + 0.2 * k)
            walk = [0, rng.choice([2, 4]), 7, rng.choice([9, 11, 6])]
            for c, iv in enumerate(walk): put(upright(broot * 2 ** (iv / 12), beat * 0.85, 0.5), t0 + c * beat)
            for c in [0, 1, 1.5, 2, 3, 3.5]: put(ride(0.10 if c % 1 else 0.14), t0 + sw(c) * beat + hum(), 0.4)
            lead = vibes
        else:  # spa
            for k, f in enumerate(chord): put(fm_pad(f / 2, bar, 0.14), t0, -0.5 + 0.33 * k)
            arp = chord + [f * 2 for f in chord[:2]]
            for i in range(8): put(bell(arp[(i * 3 + b) % len(arp)], beat, 0.1), t0 + i * beat / 2, rng.uniform(-0.7, 0.7))
            lead = bell
        # тема вступает со второго круга и замолкает на последнем, чтобы луп «дышал»
    for b, pos, m, ln in mel:
        if 4 <= b < bars - 2 or (style == "spa" and b >= 2):
            put(lead(hz(m), ln * beat * 0.95, 0.24) if lead is not fm_rhodes else fm_rhodes(hz(m), ln * beat * 0.9, 0.24, 1.3),
                b * bar + sw(pos) * beat + hum(), 0.2)

    mix = np.stack([L, R], 1)
    # «лифтовая» комната: короткий синтетический ревер через свёртку
    ir_n = int(1.3 * SR); nz = np.random.randn(ir_n, 1) * 0.5 + np.random.randn(ir_n, 2) * 0.5   # частично общий L/R — ревер не разваливается в моно
    ir = nz * np.exp(-np.arange(ir_n) / SR * 4.5)[:, None] * 0.015
    size = 1 << int(np.ceil(np.log2(N + ir_n)))
    wet = np.real(np.fft.irfft(np.fft.rfft(mix, size, axis=0) * np.fft.rfft(ir, size, axis=0), size, axis=0))
    wet = wet[:N] + np.r_[wet[N:N + ir_n], np.zeros((max(0, N - ir_n), 2))][:N]       # хвост ревера тоже в начало
    mix = mix + wet * 0.55
    spec = np.fft.rfft(mix, axis=0); fr = np.fft.rfftfreq(N, 1 / SR)[:, None]
    mix = np.fft.irfft(spec / np.sqrt(1 + (fr / 7500) ** 4), N, axis=0)            # мягкий срез верха — «динамик в лифте»
    mid, side = (mix[:, 0] + mix[:, 1]) / 2, (mix[:, 0] - mix[:, 1]) / 2
    mix = np.stack([mid + side * 1.3, mid - side * 1.3], 1)                         # чуть шире стерео
    mix = np.tanh(mix / (np.abs(mix).max() + 1e-9) * 1.4) * 0.8
    return mix, dict(style=style, key=KEYS[key], bpm=round(bpm), prog=prog_name, bars=bars, seconds=round(N / SR, 1))

def save(path, mix):
    pcm = (np.clip(mix, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())

def main():
    ap = argparse.ArgumentParser(description="Генератор лифтовой музыки")
    ap.add_argument("-n", "--count", type=int, default=5, help="сколько треков (по умолчанию 5)")
    ap.add_argument("-s", "--seconds", type=float, default=45, help="длина трека в секундах")
    ap.add_argument("--style", choices=list(STYLES), help="один стиль вместо микса")
    ap.add_argument("--seed", type=int, help="зерно — повторить конкретный трек")
    ap.add_argument("-o", "--out", default="elevator_music", help="папка для треков")
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    styles = list(STYLES)
    base = random.randrange(10**6)
    print("🛗  Лифт едет. Пишу музыку...\n")
    for i in range(a.count):
        seed = (a.seed if a.seed is not None else base) + i
        style = a.style or styles[i % len(styles)]
        mix, info = render(style, a.seconds, seed)
        name = f"{i+1:02d}_{info['style']}_{info['key']}_{info['bpm']}bpm_seed{seed}.wav"
        save(os.path.join(a.out, name), mix)
        print(f"  этаж {i+1}: {info['style']:<8} {info['key']:<3} {info['bpm']} BPM  {info['prog']:<12} {info['seconds']} с  → {name}")
    print(f"\nГотово. Треки в папке {a.out}/ — каждый закольцован, ставь на повтор.")

if __name__ == "__main__":
    main()
