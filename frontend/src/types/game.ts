// Wire types mirroring backend/api/websocket.py and backend/game/*.to_dict().

export type StructureRole = 'barrier' | 'defense_tower' | 'heavy_fortification' | 'support_tower' | 'custom';
export type Behavior = 'attack' | 'block' | 'support';
export type EnemyType = 'scout' | 'tank' | 'saboteur' | 'boss';
export type GameStatus = 'idle' | 'running' | 'paused' | 'wave_ended' | 'victory' | 'game_over';
export type AbilityName = 'strike' | 'emp' | 'repair';
export type StreamVariant = 'overlay' | 'raw' | 'warped';

export interface Structure {
  id: string;
  object_id: string;
  detected_class: string;
  role: StructureRole;
  behavior: Behavior;
  x: number;
  y: number;
  w: number;
  h: number;
  health: number;
  max_health: number;
  level: number;
  range: number;
  damage: number;
  fire_rate: number;
  slow_radius: number;
  buff_radius: number;
  blocks_path: boolean;
  confidence: number;
  source: string;
  stale: boolean;
  active: boolean;
  destroyed: boolean;
  buffed: boolean;
  disabled_for: number;
  aim: number;
  kills: number;
  damage_dealt: number;
  cost: number;
  upgrade_cost: number | null;
}

export interface Enemy {
  id: string;
  type: EnemyType;
  x: number;
  y: number;
  r: number;
  health: number;
  max_health: number;
  intent: string;
  path: [number, number][];
  heading: number;
  stunned: boolean;
  slowed: boolean;
  attacking: string | null;
  target: string | null;
}

export interface Projectile {
  id: string;
  x: number;
  y: number;
  tx: number;
  ty: number;
  k: 'bolt' | 'heavy';
}

export interface AbilityState {
  label: string;
  cost: number;
  cooldown: number;
  radius: number;
  ready_in: number;
}

export interface WaveSummary {
  wave_number: number;
  enemies_defeated: number;
  enemies_total: number;
  enemies_leaked: number;
  damage_received: number;
  base_health_remaining: number;
  base_health_max: number;
  score_earned: number;
  credits_earned: number;
  structures_used: number;
  structures_destroyed: number;
  route_length_ratio: number;
  sabotages: number;
  abilities_used: number;
  ai_difficulty: string;
  ai_difficulty_value: number;
  difficulty_change: 'up' | 'down' | 'same';
  strategy_impact: string[];
  suggestions: string[];
  wave_clear_bonus?: number;
}

export interface FinalResult {
  outcome: 'victory' | 'defeat';
  reason: string;
  score: number;
  wave_reached: number;
  total_waves: number;
  kills: number;
  base_health: number;
  waves: WaveSummary[];
  player: string;
  difficulty: number;
}

export interface GameSnapshot {
  status: GameStatus;
  wave: number;
  total_waves: number;
  time: number;
  tick: number;
  base: { x: number; y: number; radius: number; health: number; max_health: number };
  score: number;
  credits: number;
  kills: number;
  player_name: string;
  difficulty: { value: number; label: string; min: number; max: number };
  spawn_points: [number, number][];
  battlefield: { width: number; height: number };
  structures: Structure[];
  enemies: Enemy[];
  projectiles: Projectile[];
  abilities: Record<AbilityName, AbilityState>;
  wave_progress: { spawned: number; total: number; alive: number; killed: number; leaked: number };
  nav: { version: number; no_path: boolean; cell: number };
  last_summary: WaveSummary | null;
  final_result: FinalResult | null;
  perf: { tick_ms: number; hz: number };
}

export interface CustomConfig {
  behavior: Behavior;
  durability?: number | null;
  range?: number | null;
  damage?: number | null;
  fire_rate?: number | null;
  cost?: number | null;
}

export interface TrackedObject {
  id: string;
  detected_class: string;
  confidence: number;
  source: 'yolo' | 'shape' | 'simulated' | string;
  bbox: number[] | null;
  center: [number, number];
  footprint: [number, number];
  role: StructureRole;
  default_role: StructureRole;
  is_manual_role: boolean;
  custom: CustomConfig | null;
  confirmed: boolean;
  is_stale: boolean;
  stale_seconds: number;
  removal_in: number | null;
  last_seen: number;
  move_count: number;
  last_moved_at: number;
}

export interface CameraStatus {
  state: 'disconnected' | 'connecting' | 'streaming' | 'reconnecting' | 'error' | 'stalled';
  connected: boolean;
  camera_id: number | string | null;
  camera_name: string;
  is_continuity: boolean;
  is_simulated: boolean;
  fps: number;
  resolution: [number, number] | null;
  requested_resolution: [number, number];
  frame_count: number;
  last_frame_age_s: number | null;
  reconnect_attempts: number;
  error: string | null;
  permission: string;
  troubleshooting?: string[];
}

export interface PipelineStatus {
  running: boolean;
  detection_fps: number;
  target_detection_fps: number;
  inference_ms: number;
  raw_detections: number;
  model_status: 'not_loaded' | 'loading' | 'ready' | 'error';
  model_device: string;
  model_error: string | null;
  shape_reference: boolean;
  shape_detection_enabled: boolean;
  low_performance_mode: boolean;
  message: string | null;
  camera_motion: { state: 'no_reference' | 'stable' | 'moved' | 'uncertain'; shift: number; checked_at: number };
}

export interface SimObject {
  id: string;
  kind: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface VisionSnapshot {
  objects: TrackedObject[];
  suppressed: { id: string; class: string; center: [number, number] }[];
  camera: CameraStatus;
  pipeline: PipelineStatus;
  calibration: { is_calibrated: boolean; version: number; frame_size: [number, number] | null };
  sim_objects?: SimObject[];
}

export interface CameraDevice {
  id: number | string;
  index: number | null;
  name: string;
  unique_id: string;
  model_id: string;
  device_type: string;
  is_continuity: boolean;
  is_desk_view: boolean;
  is_simulated: boolean;
  discovery: string;
}

export interface GameEvent {
  type: string;
  t: number;
  [key: string]: unknown;
}

export interface RoleStats {
  label: string;
  behavior: Behavior;
  cost: number;
  durability: number;
  blocks_path: boolean;
  range: number;
  damage: number;
  fire_rate: number;
  slow_factor: number;
  slow_radius: number;
  buff_radius: number;
  buff_damage_multiplier: number;
}

export interface GameConfig {
  roles: Record<StructureRole, RoleStats>;
  role_mappings: Record<string, StructureRole>;
  abilities: Record<AbilityName, { label: string; cost: number; cooldown: number; radius: number }>;
  upgrade_costs: number[];
  battlefield: { width: number; height: number };
}

export interface HighScore {
  name: string;
  score: number;
  wave: number;
  outcome: string;
  kills: number;
  difficulty: number;
  date: string;
}
