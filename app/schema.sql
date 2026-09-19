-- MagicLink schema (SQLite)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  username       TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash  TEXT NOT NULL,
  display_name   TEXT NOT NULL DEFAULT '',
  avatar         TEXT NOT NULL DEFAULT '',
  public_enabled INTEGER NOT NULL DEFAULT 0,
  -- 对外公开页地址。NULL = 用 /u/<用户名>；设了就优先用它
  public_slug    TEXT,
  -- GitCode 登录：存对方的用户 id（字符串）。NULL = 没绑定
  gitcode_id     TEXT,
  created_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_gitcode
  ON users(gitcode_id) WHERE gitcode_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_public_slug
  ON users(public_slug) WHERE public_slug IS NOT NULL;

CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS teams (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  name           TEXT NOT NULL,
  owner_id       INTEGER NOT NULL REFERENCES users(id),
  invite_code    TEXT NOT NULL UNIQUE,
  public_enabled INTEGER NOT NULL DEFAULT 0,
  public_slug    TEXT,
  created_at     TEXT NOT NULL
);
-- 公开页地址：可读可猜（如 /t/doc-team），留空则用 team-<id>
CREATE UNIQUE INDEX IF NOT EXISTS idx_teams_public_slug
  ON teams(public_slug) WHERE public_slug IS NOT NULL;

CREATE TABLE IF NOT EXISTS team_members (
  team_id   INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role      TEXT NOT NULL CHECK (role IN ('owner','admin','member')),
  joined_at TEXT NOT NULL,
  PRIMARY KEY (team_id, user_id)
);

-- 分组：归属个人空间 或 归属团队空间，二选一
CREATE TABLE IF NOT EXISTS groups (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  scope         TEXT NOT NULL CHECK (scope IN ('personal','team')),
  owner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  team_id       INTEGER REFERENCES teams(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  position      INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL,
  CHECK ((scope = 'personal' AND owner_user_id IS NOT NULL AND team_id IS NULL)
      OR (scope =  'team'     AND team_id       IS NOT NULL AND owner_user_id IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_groups_personal ON groups(owner_user_id, position);
CREATE INDEX IF NOT EXISTS idx_groups_team ON groups(team_id, position);

-- 链接：team_id 为 NULL = 个人链接；否则为团队链接
CREATE TABLE IF NOT EXISTS links (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  team_id             INTEGER REFERENCES teams(id) ON DELETE CASCADE,
  group_id            INTEGER REFERENCES groups(id) ON DELETE SET NULL,
  url                 TEXT NOT NULL,
  title               TEXT NOT NULL DEFAULT '',
  description         TEXT NOT NULL DEFAULT '',
  tags                TEXT NOT NULL DEFAULT '[]',
  favicon             TEXT NOT NULL DEFAULT '',
  copied_from_link_id INTEGER REFERENCES links(id) ON DELETE SET NULL,
  -- 第三个独立开关：对外公开（匿名可见，不需要登录）
  public_show         INTEGER NOT NULL DEFAULT 0,
  -- 组内顺序（拖拽排序用）。同一个分组里的链接按这个值升序排。
  -- 全部为 0 的组（从没拖过）退化成按 updated_at 倒序，和加拖拽之前的表现一致。
  position            INTEGER NOT NULL DEFAULT 0,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_links_personal ON links(owner_user_id, team_id);
CREATE INDEX IF NOT EXISTS idx_links_team ON links(team_id);

-- 个人链接 -> 团队的可见性
--   in_space   = 放进团队链接列表（唯一在用的开关）
--   in_profile = 已废弃：「队友进我主页可见」那个功能已下线（对外有公开页了，
--                这个中间态多余）。列保留只为不破坏已有数据，写入时镜像 in_space。
CREATE TABLE IF NOT EXISTS link_team_links (
  link_id       INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
  team_id       INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  in_space      INTEGER NOT NULL DEFAULT 0,
  in_profile    INTEGER NOT NULL DEFAULT 0,
  team_group_id INTEGER REFERENCES groups(id) ON DELETE SET NULL,
  -- 这条链接在该团队分组里的顺序（和 links.position 是两套：同一条个人链接
  -- 在自己的个人分组里有一个位置，在团队的某个分组里又有另一个位置）
  position      INTEGER NOT NULL DEFAULT 0,
  created_by    INTEGER NOT NULL REFERENCES users(id),
  created_at    TEXT NOT NULL,
  PRIMARY KEY (link_id, team_id)
);
CREATE INDEX IF NOT EXISTS idx_ltl_team ON link_team_links(team_id, in_space, in_profile);
