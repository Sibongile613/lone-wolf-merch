"""Lone Wolf Labs v2 — Stealth Shadow & OSU Campus Cover Bot (mechfight/1)."""
from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

import mechfight as mf


def _wrap_angle(angle: float) -> float:
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def _dist2d(a: List[float], b: List[float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _point_in_ring(px: float, py: float, ring: List[float]) -> bool:
    n = len(ring) // 2
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[2 * i], ring[2 * i + 1]
        xj, yj = ring[2 * j], ring[2 * j + 1]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _dist_seg_sq(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    c1 = vx * wx + vy * wy
    if c1 <= 0.0:
        return wx * wx + wy * wy
    c2 = vx * vx + vy * vy
    if c2 <= c1:
        dx, dy = px - bx, py - by
        return dx * dx + dy * dy
    t = c1 / c2
    projx, projy = ax + t * vx, ay + t * vy
    dx, dy = px - projx, py - projy
    return dx * dx + dy * dy


class ArenaMap:
    """Fast 2D building footprint & cover lookup built from /arena/v2/world.json."""

    def __init__(self, map_dir: str) -> None:
        self.buildings: List[Tuple[float, float, float, float, float, List[float], List[List[float]]]] = []
        self.grid_step: float = 6.0
        self.min_x: float = -650.0
        self.min_y: float = -500.0
        self.nx: int = 0
        self.ny: int = 0
        self.blocked: bytearray = bytearray()
        self._load(map_dir)

    def _load(self, map_dir: str) -> None:
        world_path = os.path.join(map_dir, "v2", "world.json")
        if not os.path.exists(world_path):
            return
        try:
            with open(world_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        prisms = data.get("prisms", [])
        b_min_x, b_min_y = 1e9, 1e9
        b_max_x, b_max_y = -1e9, -1e9

        for p in prisms:
            kind = p.get("kind", "building")
            base = float(p.get("base", 0.0))
            top = float(p.get("top", 10.0))
            # Bridges with base >= 9.2m can be walked under freely
            if kind == "bridge" and base >= 9.2:
                continue
            if top - base < 1.5:
                continue
            ring = p.get("ring", [])
            if len(ring) < 6:
                continue
            xs = ring[0::2]
            ys = ring[1::2]
            minx, maxx = min(xs), max(xs)
            miny, maxy = min(ys), max(ys)
            b_min_x = min(b_min_x, minx)
            b_min_y = min(b_min_y, miny)
            b_max_x = max(b_max_x, maxx)
            b_max_y = max(b_max_y, maxy)
            holes = p.get("holes", [])
            self.buildings.append((minx, miny, maxx, maxy, base, ring, holes))

        if not self.buildings:
            return

        self.min_x = b_min_x - 30.0
        self.min_y = b_min_y - 30.0
        self.nx = int((b_max_x - b_min_x + 60.0) / self.grid_step) + 2
        self.ny = int((b_max_y - b_min_y + 60.0) / self.grid_step) + 2
        self.blocked = bytearray(self.nx * self.ny)

        for minx, miny, maxx, maxy, _base, ring, holes in self.buildings:
            i0 = max(0, int((minx - 3.0 - self.min_x) / self.grid_step))
            i1 = min(self.nx - 1, int((maxx + 3.0 - self.min_x) / self.grid_step) + 1)
            j0 = max(0, int((miny - 3.0 - self.min_y) / self.grid_step))
            j1 = min(self.ny - 1, int((maxy + 3.0 - self.min_y) / self.grid_step) + 1)
            for j in range(j0, j1 + 1):
                wy = self.min_y + j * self.grid_step
                row = j * self.nx
                for i in range(i0, i1 + 1):
                    if self.blocked[row + i]:
                        continue
                    wx = self.min_x + i * self.grid_step
                    if self._point_hits_building(wx, wy, ring, holes, pad=2.8):
                        self.blocked[row + i] = 1

    def _point_hits_building(
        self, px: float, py: float, ring: List[float], holes: List[List[float]], pad: float
    ) -> bool:
        if _point_in_ring(px, py, ring):
            for h in holes:
                if _point_in_ring(px, py, h):
                    return False
            return True
        if pad > 0.0:
            pad_sq = pad * pad
            n = len(ring) // 2
            j = n - 1
            for i in range(n):
                if _dist_seg_sq(px, py, ring[2 * j], ring[2 * j + 1], ring[2 * i], ring[2 * i + 1]) <= pad_sq:
                    return True
                j = i
        return False

    def is_blocked(self, x: float, y: float) -> bool:
        if self.nx == 0:
            return False
        i = int(round((x - self.min_x) / self.grid_step))
        j = int(round((y - self.min_y) / self.grid_step))
        if i < 0 or i >= self.nx or j < 0 or j >= self.ny:
            return False
        return self.blocked[j * self.nx + i] != 0

    def segment_blocked(self, ax: float, ay: float, bx: float, by: float) -> bool:
        if self.nx == 0:
            return False
        dist = math.hypot(bx - ax, by - ay)
        steps = max(1, int(dist / 4.5))
        for s in range(1, steps):
            f = s / steps
            if self.is_blocked(ax + (bx - ax) * f, ay + (by - ay) * f):
                return True
        return False

    def steer_around_walls(self, x: float, y: float, tx: float, ty: float) -> Tuple[float, float]:
        """Pick an unobstructed steering direction closest to desired target (tx, ty)."""
        dx = tx - x
        dy = ty - y
        dist = math.hypot(dx, dy)
        if dist < 1e-4 or self.nx == 0:
            return dx, dy

        base_yaw = math.atan2(dy, dx)
        # Test candidate angles fanning out from desired heading
        offsets = (
            0.0, 0.25, -0.25, 0.5, -0.5, 0.8, -0.8,
            1.15, -1.15, 1.55, -1.55, 2.0, -2.0, 2.5, -2.5, math.pi
        )
        best_yaw = base_yaw
        best_score = -1e9
        lookahead = min(18.0, max(7.0, dist))

        for off in offsets:
            yaw = base_yaw + off
            ux, uy = math.cos(yaw), math.sin(yaw)
            clear = True
            for d in (4.0, 8.0, 13.0, lookahead):
                if d > lookahead:
                    break
                if self.is_blocked(x + ux * d, y + uy * d):
                    clear = False
                    break
            score = math.cos(off) * 10.0 + (25.0 if clear else -40.0)
            if score > best_score:
                best_score = score
                best_yaw = yaw

        return math.cos(best_yaw) * dist, math.sin(best_yaw) * dist

    def find_cover_spot(
        self, x: float, y: float, threat_yaw: float, zcx: float, zcy: float, zr: float
    ) -> Optional[Tuple[float, float]]:
        """Find a nearby open tile shielded by a building from threat_yaw and inside the zone."""
        if self.nx == 0:
            return None
        tx, ty = math.cos(threat_yaw), math.sin(threat_yaw)
        best_pt: Optional[Tuple[float, float]] = None
        best_score = -1e9

        for r in (12.0, 22.0, 34.0, 48.0):
            for k in range(16):
                ang = (2.0 * math.pi * k) / 16.0
                cx = x + math.cos(ang) * r
                cy = y + math.sin(ang) * r
                if self.is_blocked(cx, cy):
                    continue
                if math.hypot(cx - zcx, cy - zcy) > max(12.0, zr - 10.0):
                    continue
                # Check if a building blocks the line toward the threat direction
                shielded = False
                for sd in (6.0, 12.0, 18.0, 26.0):
                    if self.is_blocked(cx + tx * sd, cy + ty * sd):
                        shielded = True
                        break
                if not shielded:
                    continue
                # Prefer moving away from threat and close to current position
                away_dot = -(math.cos(ang) * tx + math.sin(ang) * ty)
                score = away_dot * 18.0 - r * 0.35
                if score > best_score:
                    best_score = score
                    best_pt = (cx, cy)
        return best_pt


class Bot:
    name = "lone-wolf-v2"

    def __init__(self, hello: mf.Hello) -> None:
        cfg = hello.get("config", {})
        loot_cfg = cfg.get("loot", {})
        sound_cfg = cfg.get("sound", {})
        weapons_cfg = cfg.get("weapons", {})

        self.pickup_radius: float = float(loot_cfg.get("pickup_radius", 4.0))
        self.step_speed: float = float(sound_cfg.get("step_speed", 5.0))
        self.mortar_speed: float = float(weapons_cfg.get("mortar", {}).get("speed", 72.0))
        self.mortar_gravity: float = float(weapons_cfg.get("mortar", {}).get("gravity", 22.0))

        map_info = hello.get("map", {})
        self.arena = ArenaMap(str(map_info.get("dir", "/arena")))

        self.upgrades_cfg: List[Dict[str, Any]] = cfg.get("upgrades", [])
        self.upgrade_priority: Dict[str, int] = {}
        for u in self.upgrades_cfg:
            uid = str(u.get("id", ""))
            effects = u.get("effects", [])
            score = 0
            for ef in effects:
                path = str(ef.get("path", ""))
                if "armor" in uid or "rear" in path or "max_hp" in path or "regen" in path:
                    score += 36
                if "sensor" in uid or "vision" in path or "sound" in path:
                    score += 24
                if "speed" in path or "boost" in path or "energy" in path:
                    score += 22
                if "damage" in path or "rate" in path or "cooldown" in path:
                    score += 14
            self.upgrade_priority[uid] = score

        self.last_damage_t: float = -999.0
        self.last_damage_bearing: Optional[float] = None
        self.laser_charging: List[bool] = [False, False]
        self.last_pos: Optional[Tuple[float, float]] = None
        self.stuck_ticks: int = 0

    def _pick_upgrade(self, offer: Dict[str, Any]) -> int:
        choices = offer.get("choices", [])
        if not choices:
            return 0
        best_idx = 0
        best_score = -10**9
        for idx, ch in enumerate(choices):
            uid = str(ch.get("id", ""))
            desc = str(ch.get("desc", "")).lower()
            s = self.upgrade_priority.get(uid, 0)
            if "armor" in desc or "hp" in desc or "regen" in desc:
                s += 28
            if "vision" in desc or "sensor" in desc or "sound" in desc:
                s += 18
            if "speed" in desc or "energy" in desc:
                s += 15
            if s > best_score:
                best_score = s
                best_idx = idx
        return best_idx

    def _active_zone(self, obs: mf.Observation) -> Tuple[float, float, float, float, float, float]:
        zone = obs["zone"]
        t = float(obs["t"])
        shrink_start = float(zone.get("shrink_start", t))
        shrink_end = float(zone.get("shrink_end", t + 1.0))
        cur_c = zone.get("center", [0.0, 0.0])
        cur_r = float(zone.get("radius", 500.0))
        nxt_c = zone.get("next_center", cur_c)
        nxt_r = float(zone.get("next_radius", cur_r))

        if t >= shrink_start:
            frac = max(0.0, min(1.0, (t - shrink_start) / max(1e-6, shrink_end - shrink_start)))
            cx = cur_c[0] + (nxt_c[0] - cur_c[0]) * frac
            cy = cur_c[1] + (nxt_c[1] - cur_c[1]) * frac
            rad = cur_r + (nxt_r - cur_r) * frac
        else:
            cx, cy, rad = float(cur_c[0]), float(cur_c[1]), cur_r
        return cx, cy, rad, float(nxt_c[0]), float(nxt_c[1]), nxt_r

    def _mortar_pitch(self, horiz_dist: float, dz: float) -> Optional[float]:
        v = self.mortar_speed
        g = self.mortar_gravity
        v2 = v * v
        disc = v2 * v2 - g * (g * horiz_dist * horiz_dist + 2.0 * dz * v2)
        if disc < 0.0 or horiz_dist < 1.0:
            return None
        # Low-arc solution for faster time-to-target
        tan_theta = (v2 - math.sqrt(disc)) / (g * horiz_dist)
        return math.atan(tan_theta)

    def _weapon_rank(self, kind: Optional[str]) -> int:
        if kind == "laser":
            return 4
        if kind == "lightning":
            return 3
        if kind == "mortar":
            return 2
        if kind == "gun":
            return 1
        return 0

    def _weapon_fire_decision(
        self,
        slot_idx: int,
        w: Optional[mf.WeaponObs],
        dist: float,
        has_target: bool,
        los_clear: bool,
        energy: float,
        target_has_mortar: bool,
    ) -> bool:
        if w is None or not has_target:
            self.laser_charging[slot_idx] = False
            return False

        kind = w.get("kind")
        stats = w.get("stats", {})
        max_range = float(stats.get("range", 200.0))

        # Mortar can lob over walls; other weapons need line of sight
        if kind != "mortar" and not los_clear:
            self.laser_charging[slot_idx] = False
            return False

        if kind == "gun":
            ammo = float(w.get("ammo", 0.0))
            reload_left = float(w.get("reload", 0.0))
            if reload_left > 0.0 or ammo <= 0.0:
                return False
            return dist <= max_range * 0.92

        if kind == "lightning":
            if energy < 10.0 or dist > min(44.5, max_range):
                return False
            return float(w.get("cooldown", 0.0)) <= 0.05

        if kind == "mortar":
            if dist < 24.0 or dist > min(225.0, max_range):
                return False
            return float(w.get("cooldown", 0.0)) <= 0.05

        if kind == "laser":
            charge_time = float(w.get("charge", 0.0))
            full_charge = float(stats.get("charge", 0.75))
            if dist > max_range:
                self.laser_charging[slot_idx] = False
                return False
            target_charge = full_charge * (0.85 if target_has_mortar else 0.98)
            if not self.laser_charging[slot_idx]:
                if float(w.get("cooldown", 0.0)) <= 0.05 and energy > 12.0:
                    self.laser_charging[slot_idx] = True
                    return True
                return False
            if charge_time >= target_charge:
                self.laser_charging[slot_idx] = False
                return False
            return True

        return False

    def act(self, obs: mf.Observation) -> mf.Action:
        me = obs["self"]
        x, y, z = float(me["pos"][0]), float(me["pos"][1]), float(me["pos"][2])
        hp = float(me.get("hp", 1400.0))
        max_hp = max(1.0, float(me.get("max_hp", 1400.0)))
        hp_ratio = hp / max_hp
        energy = float(me.get("energy", 0.0))
        in_zone = bool(me.get("in_zone", True))
        t = float(obs["t"])
        alive = int(obs.get("alive", 16))
        my_cubes = int(me.get("cubes", 0))
        stats = me.get("stats", {})
        walk_speed = float(stats.get("walk_speed", 11.7))
        muzzle_h = float(stats.get("muzzle_height", 7.0))

        if self.last_pos is not None and math.hypot(x - self.last_pos[0], y - self.last_pos[1]) < 0.12:
            self.stuck_ticks += 1
        else:
            self.stuck_ticks = 0
        self.last_pos = (x, y)

        for ev in obs.get("events", []):
            if ev.get("type") == "damaged":
                self.last_damage_t = t
                if ev.get("bearing") is not None:
                    self.last_damage_bearing = float(ev["bearing"])

        act: mf.Action = {"tick": obs["tick"]}

        if obs.get("offer"):
            act["pick"] = self._pick_upgrade(obs["offer"])  # type: ignore[arg-type]

        weapons = me.get("weapons", [None, None])
        w0 = weapons[0] if len(weapons) > 0 else None
        w1 = weapons[1] if len(weapons) > 1 else None
        held_kinds = {w.get("kind") for w in (w0, w1) if w is not None}

        # Reload gun early when not in immediate close fight
        for w in (w0, w1):
            if w and w.get("kind") == "gun":
                ammo = float(w.get("ammo", 0.0))
                mag = float(w.get("stats", {}).get("mag", 12.0))
                if float(w.get("reload", 0.0)) <= 0.0 and ammo <= max(3.0, mag * 0.35):
                    act["reload"] = True

        # Smart weapon looting: fill empty slot or upgrade gun -> laser/lightning/mortar
        for p in obs.get("pickups", []):
            pkind = p.get("kind")
            if pkind in held_kinds or _dist2d(p["pos"], [x, y]) > self.pickup_radius:
                continue
            if w1 is None or w0 is None:
                act["take"] = p["id"]
                break
            # Replace weakest slot (usually gun) if pickup is strictly better and not charging laser
            r_new = self._weapon_rank(pkind)
            r0 = self._weapon_rank(w0.get("kind"))
            r1 = self._weapon_rank(w1.get("kind"))
            if r_new > min(r0, r1):
                drop_slot = 0 if r0 <= r1 else 1
                if not self.laser_charging[drop_slot]:
                    act["take"] = p["id"]
                    act["drop"] = drop_slot
                    break

        zcx, zcy, zrad, ncx, ncy, nrad = self._active_zone(obs)
        dist_to_zone_center = math.hypot(x - zcx, y - zcy)
        dist_to_next_center = math.hypot(x - ncx, y - ncy)
        zone_urgent = (not in_zone) or (dist_to_zone_center > zrad - 24.0) or (dist_to_next_center > nrad + 35.0)

        mechs = obs.get("mechs", [])
        hostile_mechs = [m for m in mechs if m.get("kind") == "mech"]
        hostile_mechs.sort(key=lambda m: _dist2d(m["pos"], [x, y]))
        npcs = [m for m in mechs if m.get("kind") == "npc"]
        npcs.sort(key=lambda m: _dist2d(m["pos"], [x, y]))

        crates = obs.get("crates", [])
        crates.sort(key=lambda c: _dist2d(c["pos"], [x, y]))
        cubes = obs.get("cubes", [])
        cubes.sort(key=lambda c: _dist2d(c["pos"], [x, y]))
        pickups = [p for p in obs.get("pickups", []) if p.get("kind") not in held_kinds]
        pickups.sort(key=lambda p: _dist2d(p["pos"], [x, y]))

        recently_hit = (t - self.last_damage_t) < 4.5
        low_hp = hp_ratio < 0.52
        nearest_enemy = hostile_mechs[0] if hostile_mechs else None
        nearest_enemy_dist = _dist2d(nearest_enemy["pos"], [x, y]) if nearest_enemy else 999.0

        # Check active supply drops (free +3 cubes + FULL HEAL if alone for 4s!)
        best_drop = None
        for d in obs.get("drops", []):
            ddist = _dist2d(d["pos"], [x, y])
            if ddist < 140.0 and float(d.get("lands_in", 99.0)) <= 18.0 and nearest_enemy_dist > 55.0:
                best_drop = d
                break

        # --- GOAL & STEALTH MOVEMENT SELECTION ---
        goal_x, goal_y = ncx, ncy
        stealth_walk = True
        mode_label = "stealth-zone"

        if zone_urgent:
            goal_x, goal_y = ncx, ncy
            stealth_walk = dist_to_zone_center < zrad - 12.0 and not recently_hit
            mode_label = "zone-rotate"
        elif best_drop is not None and not low_hp:
            goal_x, goal_y = float(best_drop["pos"][0]), float(best_drop["pos"][1])
            stealth_walk = float(best_drop.get("lands_in", 0.0)) > 2.5
            mode_label = "supply-drop"
        elif (low_hp or len(hostile_mechs) >= 2) and (nearest_enemy is not None or recently_hit):
            # Duck behind the nearest campus building to break line-of-sight and trigger 45 HP/s regen!
            threat_yaw = (
                math.atan2(nearest_enemy["pos"][1] - y, nearest_enemy["pos"][0] - x)
                if nearest_enemy is not None
                else (self.last_damage_bearing if self.last_damage_bearing is not None else math.atan2(y - ncy, x - ncx))
            )
            cover = self.arena.find_cover_spot(x, y, threat_yaw, zcx, zcy, zrad)
            if cover is not None:
                goal_x, goal_y = cover
                stealth_walk = False
                mode_label = "take-cover"
            else:
                goal_x = x - math.cos(threat_yaw) * 45.0
                goal_y = y - math.sin(threat_yaw) * 45.0
                stealth_walk = False
                mode_label = "evade"
        elif cubes and _dist2d(cubes[0]["pos"], [x, y]) < 55.0 and nearest_enemy_dist > 50.0:
            goal_x, goal_y = float(cubes[0]["pos"][0]), float(cubes[0]["pos"][1])
            stealth_walk = nearest_enemy_dist > 70.0
            mode_label = "loot-cube"
        elif pickups and (w1 is None or self._weapon_rank(pickups[0].get("kind")) > 1) and _dist2d(pickups[0]["pos"], [x, y]) < 55.0 and nearest_enemy_dist > 55.0:
            goal_x, goal_y = float(pickups[0]["pos"][0]), float(pickups[0]["pos"][1])
            stealth_walk = True
            mode_label = "loot-weapon"
        elif crates and my_cubes < 10 and _dist2d(crates[0]["pos"], [x, y]) < 65.0 and nearest_enemy_dist > 65.0 and alive > 5:
            goal_x, goal_y = float(crates[0]["pos"][0]), float(crates[0]["pos"][1])
            stealth_walk = True
            mode_label = "farm-crate"
        elif nearest_enemy is not None and (alive <= 4 or nearest_enemy_dist < 58.0):
            # Late-game duel or close-quarters defense: kite at optimal range around cover
            ex, ey = float(nearest_enemy["pos"][0]), float(nearest_enemy["pos"][1])
            to_e = math.atan2(ey - y, ex - x)
            strafe = 1.0 if (int(obs["tick"]) // 25) % 2 == 0 else -1.0
            desired = 38.0 if "lightning" in held_kinds else 85.0
            radial = -0.6 if nearest_enemy_dist < desired * 0.8 else (0.35 if nearest_enemy_dist > desired * 1.3 else 0.0)
            goal_x = x + math.cos(to_e) * radial * 30.0 + math.cos(to_e + strafe * 1.57) * 28.0
            goal_y = y + math.sin(to_e) * radial * 30.0 + math.sin(to_e + strafe * 1.57) * 28.0
            stealth_walk = False
            mode_label = "combat-kite"
        else:
            # Stay quietly inside safe zone near cover; hold still if already well-positioned to make zero sound!
            if dist_to_next_center < max(15.0, nrad * 0.65) and not self.arena.is_blocked(x, y):
                goal_x, goal_y = x, y
                mode_label = "ambush-hold"
            else:
                goal_x, goal_y = ncx, ncy
                stealth_walk = True
                mode_label = "silent-drift"

        # Steer cleanly around OSU campus buildings
        steer_dx, steer_dy = self.arena.steer_around_walls(x, y, goal_x, goal_y)
        steer_dist = math.hypot(steer_dx, steer_dy)

        if steer_dist > 1.2:
            # Keep speed just under sound.step_speed (5.0 m/s) during stealth so house bots never hear footsteps!
            silent_scale = min(0.95, (self.step_speed * 0.92) / max(1.0, walk_speed))
            speed_scale = silent_scale if stealth_walk else 1.0
            act["move"] = [(steer_dx / steer_dist) * speed_scale, (steer_dy / steer_dist) * speed_scale]
        else:
            act["move"] = [0.0, 0.0]

        should_boost = (
            (not in_zone and energy > 15.0)
            or (recently_hit and low_hp and energy > 25.0)
            or (self.stuck_ticks > 8 and energy > 30.0)
        )
        act["boost"] = bool(should_boost)
        act["jump"] = bool(me.get("grounded", False) and (self.stuck_ticks > 10 or (mode_label == "combat-kite" and int(obs["tick"]) % 45 == 0)))

        # --- TARGETING & DISCIPLINED FIRE (DON'T PROVOKE THE SQUAD EARLY!) ---
        # Only shoot a mech if:
        # 1) Final 4 mechs alive, OR
        # 2) Enemy is within 68m / already damaged us, OR
        # 3) Enemy is weak (<50% HP) and isolated (1 visible mech) for a clean cube harvest
        engage_mech = None
        if nearest_enemy is not None:
            e_hp_ratio = float(nearest_enemy.get("hp", 1000.0)) / max(1.0, float(nearest_enemy.get("max_hp", 1400.0)))
            if (
                alive <= 4
                or nearest_enemy_dist <= 68.0
                or recently_hit
                or (len(hostile_mechs) == 1 and e_hp_ratio < 0.48 and nearest_enemy_dist <= 135.0)
            ):
                engage_mech = nearest_enemy

        if engage_mech is not None:
            tpos = engage_mech["pos"]
            tvel = engage_mech.get("vel", [0.0, 0.0, 0.0])
            horiz_dist = max(1.0, _dist2d(tpos, [x, y]))
            lead_t = min(0.85, horiz_dist / 230.0)
            px = float(tpos[0]) + float(tvel[0]) * lead_t
            py = float(tpos[1]) + float(tvel[1]) * lead_t
            pz = float(tpos[2]) + 4.0
            yaw = math.atan2(py - y, px - x)
            dz = pz - (z + muzzle_h)
            pitch = math.atan2(dz, horiz_dist)

            # Use exact ballistic arc if firing mortar
            if any(w and w.get("kind") == "mortar" for w in (w0, w1)):
                mp = self._mortar_pitch(horiz_dist, dz)
                if mp is not None:
                    pitch = mp

            act["aim"] = [yaw, max(-0.85, min(0.85, pitch))]
            los_clear = not self.arena.segment_blocked(x, y, float(tpos[0]), float(tpos[1]))
            target_has_mortar = "mortar" in engage_mech.get("weapons", [])
            f0 = self._weapon_fire_decision(0, w0, horiz_dist, True, los_clear, energy, target_has_mortar)
            f1 = self._weapon_fire_decision(1, w1, horiz_dist, True, los_clear, energy, target_has_mortar)
            act["fire"] = [f0, f1]
            mf.draw.line([x, y, z + muzzle_h], [px, py, pz], "#ff5040")
        elif crates and _dist2d(crates[0]["pos"], [x, y]) <= 42.0 and nearest_enemy_dist > 75.0 and alive > 4:
            # Break nearby crate quietly for +1 cube & weapon drop
            cpos = crates[0]["pos"]
            cdist = max(1.0, _dist2d(cpos, [x, y]))
            yaw = math.atan2(float(cpos[1]) - y, float(cpos[0]) - x)
            pitch = max(-0.85, min(0.85, math.atan2((float(cpos[2]) + 1.2) - (z + muzzle_h), cdist)))
            act["aim"] = [yaw, pitch]
            los_clear = not self.arena.segment_blocked(x, y, float(cpos[0]), float(cpos[1]))
            # Use gun/lightning on crates (save laser cooldown)
            f0 = self._weapon_fire_decision(0, w0 if w0 and w0.get("kind") in ("gun", "lightning") else None, cdist, True, los_clear, energy, False)
            f1 = self._weapon_fire_decision(1, w1 if w1 and w1.get("kind") in ("gun", "lightning") else None, cdist, True, los_clear, energy, False)
            act["fire"] = [f0, f1]
        elif npcs and _dist2d(npcs[0]["pos"], [x, y]) <= 42.0 and nearest_enemy_dist > 85.0 and my_cubes < 8 and alive > 5:
            # Farm isolated NPC drone for +2 cubes
            npos = npcs[0]["pos"]
            ndist = max(1.0, _dist2d(npos, [x, y]))
            yaw = math.atan2(float(npos[1]) - y, float(npos[0]) - x)
            pitch = max(-0.85, min(0.85, math.atan2((float(npos[2]) + 1.8) - (z + muzzle_h), ndist)))
            act["aim"] = [yaw, pitch]
            los_clear = not self.arena.segment_blocked(x, y, float(npos[0]), float(npos[1]))
            f0 = self._weapon_fire_decision(0, w0, ndist, True, los_clear, energy, False)
            f1 = self._weapon_fire_decision(1, w1, ndist, True, los_clear, energy, False)
            act["fire"] = [f0, f1]
        else:
            self.laser_charging = [False, False]
            act["fire"] = [False, False]
            # Look toward last damage bearing or slowly sweep torso to use 120° vision cone
            if recently_hit and self.last_damage_bearing is not None:
                act["aim"] = [_wrap_angle(self.last_damage_bearing), 0.0]
            else:
                sweep = math.sin(t * 1.1) * 0.9
                base_look = math.atan2(steer_dy, steer_dx) if steer_dist > 1.0 else math.atan2(ncy - y, ncx - x)
                act["aim"] = [_wrap_angle(base_look + sweep), 0.0]

        mf.draw.point([goal_x, goal_y, z], "#40c0ff", 6)
        mf.draw.label(f"v2:{mode_label} hp:{hp:.0f} c:{my_cubes}")
        return act


mf.run(Bot)