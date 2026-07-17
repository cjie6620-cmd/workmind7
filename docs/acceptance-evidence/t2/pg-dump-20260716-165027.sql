--
-- PostgreSQL database dump
--

\restrict GnTO4YPeLyDkl5nWCzHm2mp4EGIUv2Xt3gcWhFTVhsYHr02dGXZwUzGBR4k2cWG

-- Dumped from database version 16.14 (Debian 16.14-1.pgdg12+1)
-- Dumped by pg_dump version 16.14 (Debian 16.14-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

ALTER TABLE IF EXISTS ONLY public.rag_chunks DROP CONSTRAINT IF EXISTS fk_rag_chunks_document;
ALTER TABLE IF EXISTS ONLY public.documents DROP CONSTRAINT IF EXISTS fk_documents_owner;
DROP INDEX IF EXISTS public.uq_approval_user_request;
DROP INDEX IF EXISTS public.ix_conversations_user_id;
DROP INDEX IF EXISTS public.idx_rag_chunks_embedding_hnsw;
DROP INDEX IF EXISTS public.idx_rag_chunks_doc_id;
DROP INDEX IF EXISTS public.idx_monitor_records_time;
DROP INDEX IF EXISTS public.idx_monitor_records_feature;
DROP INDEX IF EXISTS public.idx_documents_owner_created;
DROP INDEX IF EXISTS public.idx_conversations_session;
DROP INDEX IF EXISTS public.idx_approval_user_created;
DROP INDEX IF EXISTS public.idx_approval_status;
DROP INDEX IF EXISTS public.idx_approval_session;
DROP INDEX IF EXISTS public.idx_agent_configs_type;
DROP INDEX IF EXISTS public.idx_agent_configs_active;
ALTER TABLE IF EXISTS ONLY public.users DROP CONSTRAINT IF EXISTS users_username_key;
ALTER TABLE IF EXISTS ONLY public.users DROP CONSTRAINT IF EXISTS users_pkey;
ALTER TABLE IF EXISTS ONLY public.rag_chunks DROP CONSTRAINT IF EXISTS uq_rag_chunks_doc_chunk;
ALTER TABLE IF EXISTS ONLY public.t2_backup_probe DROP CONSTRAINT IF EXISTS t2_backup_probe_pkey;
ALTER TABLE IF EXISTS ONLY public.system_settings DROP CONSTRAINT IF EXISTS system_settings_pkey;
ALTER TABLE IF EXISTS ONLY public.rag_chunks DROP CONSTRAINT IF EXISTS rag_chunks_pkey;
ALTER TABLE IF EXISTS ONLY public.monitor_records DROP CONSTRAINT IF EXISTS monitor_records_pkey;
ALTER TABLE IF EXISTS ONLY public.documents DROP CONSTRAINT IF EXISTS documents_pkey;
ALTER TABLE IF EXISTS ONLY public.conversations DROP CONSTRAINT IF EXISTS conversations_pkey;
ALTER TABLE IF EXISTS ONLY public.approval_records DROP CONSTRAINT IF EXISTS approval_records_pkey;
ALTER TABLE IF EXISTS ONLY public.alembic_version DROP CONSTRAINT IF EXISTS alembic_version_pkc;
ALTER TABLE IF EXISTS ONLY public.agent_configs DROP CONSTRAINT IF EXISTS agent_configs_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_configs DROP CONSTRAINT IF EXISTS agent_configs_name_key;
ALTER TABLE IF EXISTS public.monitor_records ALTER COLUMN id DROP DEFAULT;
DROP TABLE IF EXISTS public.users;
DROP TABLE IF EXISTS public.t2_backup_probe;
DROP TABLE IF EXISTS public.system_settings;
DROP TABLE IF EXISTS public.rag_chunks;
DROP SEQUENCE IF EXISTS public.monitor_records_id_seq;
DROP TABLE IF EXISTS public.monitor_records;
DROP TABLE IF EXISTS public.documents;
DROP TABLE IF EXISTS public.conversations;
DROP TABLE IF EXISTS public.approval_records;
DROP TABLE IF EXISTS public.alembic_version;
DROP TABLE IF EXISTS public.agent_configs;
DROP EXTENSION IF EXISTS vector;
--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_configs; Type: TABLE; Schema: public; Owner: workmind
--

CREATE TABLE public.agent_configs (
    id uuid NOT NULL,
    config_type character varying(32) NOT NULL,
    name character varying(128) NOT NULL,
    config_json jsonb NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT timezone('UTC'::text, CURRENT_TIMESTAMP) NOT NULL,
    updated_at timestamp without time zone DEFAULT timezone('UTC'::text, CURRENT_TIMESTAMP) NOT NULL
);


ALTER TABLE public.agent_configs OWNER TO workmind;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: workmind
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO workmind;

--
-- Name: approval_records; Type: TABLE; Schema: public; Owner: workmind
--

CREATE TABLE public.approval_records (
    id uuid NOT NULL,
    session_id character varying(128) NOT NULL,
    form_type character varying(32) NOT NULL,
    form_data jsonb NOT NULL,
    flow_json jsonb NOT NULL,
    approvers jsonb NOT NULL,
    status character varying(32) NOT NULL,
    final_comment text,
    result_json jsonb,
    created_at timestamp without time zone DEFAULT timezone('UTC'::text, CURRENT_TIMESTAMP) NOT NULL,
    completed_at timestamp without time zone,
    user_id character varying(64) NOT NULL,
    request_id character varying(128)
);


ALTER TABLE public.approval_records OWNER TO workmind;

--
-- Name: COLUMN approval_records.user_id; Type: COMMENT; Schema: public; Owner: workmind
--

COMMENT ON COLUMN public.approval_records.user_id IS '申请人用户 ID，由认证上下文写入';


--
-- Name: COLUMN approval_records.request_id; Type: COMMENT; Schema: public; Owner: workmind
--

COMMENT ON COLUMN public.approval_records.request_id IS '客户端幂等请求 ID';


--
-- Name: conversations; Type: TABLE; Schema: public; Owner: workmind
--

CREATE TABLE public.conversations (
    id uuid NOT NULL,
    session_id character varying(128) NOT NULL,
    user_id character varying(64),
    role character varying(20) NOT NULL,
    content text NOT NULL,
    model character varying(64),
    tokens integer,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT timezone('UTC'::text, CURRENT_TIMESTAMP) NOT NULL
);


ALTER TABLE public.conversations OWNER TO workmind;

--
-- Name: COLUMN conversations.user_id; Type: COMMENT; Schema: public; Owner: workmind
--

COMMENT ON COLUMN public.conversations.user_id IS '所属用户 ID';


--
-- Name: documents; Type: TABLE; Schema: public; Owner: workmind
--

CREATE TABLE public.documents (
    id uuid NOT NULL,
    title character varying(256) NOT NULL,
    file_name character varying(256) NOT NULL,
    category character varying(64) DEFAULT '通用'::character varying NOT NULL,
    chunks integer DEFAULT 0 NOT NULL,
    chars integer DEFAULT 0 NOT NULL,
    preview text,
    created_at timestamp without time zone DEFAULT timezone('UTC'::text, CURRENT_TIMESTAMP) NOT NULL,
    owner_user_id character varying(64)
);


ALTER TABLE public.documents OWNER TO workmind;

--
-- Name: COLUMN documents.owner_user_id; Type: COMMENT; Schema: public; Owner: workmind
--

COMMENT ON COLUMN public.documents.owner_user_id IS '上传者；NULL 表示迁移前的共享文档';


--
-- Name: monitor_records; Type: TABLE; Schema: public; Owner: workmind
--

CREATE TABLE public.monitor_records (
    id integer NOT NULL,
    "time" timestamp without time zone NOT NULL,
    feature character varying(32) NOT NULL,
    input_tokens integer DEFAULT 0 NOT NULL,
    output_tokens integer DEFAULT 0 NOT NULL,
    cost_usd double precision DEFAULT 0 NOT NULL,
    cost_cny double precision DEFAULT 0 NOT NULL,
    latency_ms double precision DEFAULT 0 NOT NULL,
    from_cache boolean DEFAULT false NOT NULL,
    error boolean DEFAULT false NOT NULL
);


ALTER TABLE public.monitor_records OWNER TO workmind;

--
-- Name: monitor_records_id_seq; Type: SEQUENCE; Schema: public; Owner: workmind
--

CREATE SEQUENCE public.monitor_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.monitor_records_id_seq OWNER TO workmind;

--
-- Name: monitor_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: workmind
--

ALTER SEQUENCE public.monitor_records_id_seq OWNED BY public.monitor_records.id;


--
-- Name: rag_chunks; Type: TABLE; Schema: public; Owner: workmind
--

CREATE TABLE public.rag_chunks (
    id uuid NOT NULL,
    doc_id uuid NOT NULL,
    chunk_index integer NOT NULL,
    content text NOT NULL,
    embedding public.vector(1024),
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT timezone('UTC'::text, CURRENT_TIMESTAMP) NOT NULL,
    updated_at timestamp without time zone DEFAULT timezone('UTC'::text, CURRENT_TIMESTAMP) NOT NULL
);


ALTER TABLE public.rag_chunks OWNER TO workmind;

--
-- Name: system_settings; Type: TABLE; Schema: public; Owner: workmind
--

CREATE TABLE public.system_settings (
    key character varying(64) NOT NULL,
    value jsonb DEFAULT '{}'::jsonb NOT NULL,
    updated_at timestamp without time zone DEFAULT timezone('UTC'::text, CURRENT_TIMESTAMP) NOT NULL
);


ALTER TABLE public.system_settings OWNER TO workmind;

--
-- Name: COLUMN system_settings.key; Type: COMMENT; Schema: public; Owner: workmind
--

COMMENT ON COLUMN public.system_settings.key IS '配置键';


--
-- Name: COLUMN system_settings.value; Type: COMMENT; Schema: public; Owner: workmind
--

COMMENT ON COLUMN public.system_settings.value IS '配置值 JSON';


--
-- Name: COLUMN system_settings.updated_at; Type: COMMENT; Schema: public; Owner: workmind
--

COMMENT ON COLUMN public.system_settings.updated_at IS '更新时间';


--
-- Name: t2_backup_probe; Type: TABLE; Schema: public; Owner: workmind
--

CREATE TABLE public.t2_backup_probe (
    id text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.t2_backup_probe OWNER TO workmind;

--
-- Name: users; Type: TABLE; Schema: public; Owner: workmind
--

CREATE TABLE public.users (
    id character varying(64) NOT NULL,
    username character varying(64) NOT NULL,
    password_hash character varying(256) NOT NULL,
    role character varying(20) DEFAULT 'user'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT timezone('UTC'::text, CURRENT_TIMESTAMP) NOT NULL,
    is_active boolean DEFAULT true NOT NULL
);


ALTER TABLE public.users OWNER TO workmind;

--
-- Name: COLUMN users.id; Type: COMMENT; Schema: public; Owner: workmind
--

COMMENT ON COLUMN public.users.id IS '用户唯一标识，与 JWT sub 一致';


--
-- Name: COLUMN users.username; Type: COMMENT; Schema: public; Owner: workmind
--

COMMENT ON COLUMN public.users.username IS '登录用户名';


--
-- Name: COLUMN users.password_hash; Type: COMMENT; Schema: public; Owner: workmind
--

COMMENT ON COLUMN public.users.password_hash IS 'bcrypt 密码哈希';


--
-- Name: COLUMN users.role; Type: COMMENT; Schema: public; Owner: workmind
--

COMMENT ON COLUMN public.users.role IS '角色：user / admin';


--
-- Name: COLUMN users.created_at; Type: COMMENT; Schema: public; Owner: workmind
--

COMMENT ON COLUMN public.users.created_at IS '创建时间';


--
-- Name: COLUMN users.is_active; Type: COMMENT; Schema: public; Owner: workmind
--

COMMENT ON COLUMN public.users.is_active IS '账号是否允许登录和刷新令牌';


--
-- Name: monitor_records id; Type: DEFAULT; Schema: public; Owner: workmind
--

ALTER TABLE ONLY public.monitor_records ALTER COLUMN id SET DEFAULT nextval('public.monitor_records_id_seq'::regclass);


--
-- Data for Name: agent_configs; Type: TABLE DATA; Schema: public; Owner: workmind
--

COPY public.agent_configs (id, config_type, name, config_json, version, is_active, created_at, updated_at) FROM stdin;
230bfa6b-ca3b-47fc-8f24-3e88dcf341ca	prompt	前端助手	{"tags": ["前端", "技术"], "versions": [], "description": "通用前端技术问答", "systemPrompt": "你是前端开发专家，精通 Vue3、React、TypeScript。回答简洁准确，必要时给代码示例。"}	1	t	2026-07-16 08:01:36.754075	2026-07-16 08:01:36.754082
997e4b3a-ca35-4150-aebd-c2bcf99c7b25	prompt	代码 Review	{"tags": ["代码", "审查"], "versions": [], "description": "代码审查专用", "systemPrompt": "你是资深代码评审专家。审查代码时，按以下顺序输出：\\n1. 【总体评价】一句话概括\\n2. 【问题列表】按严重程度排序，每条格式：[严重/一般/建议] 具体问题\\n3. 【优化建议】具体的改进代码示例\\n语气专业，直指问题，不废话。"}	1	t	2026-07-16 08:01:36.754085	2026-07-16 08:01:36.754086
1b1cdde0-27be-4b2d-8615-3993803cd89e	prompt	简洁问答	{"tags": ["简洁"], "versions": [], "description": "简短精准的回答风格", "systemPrompt": "用最简洁的语言回答问题，不超过3句话，不用废话开场。"}	1	t	2026-07-16 08:01:36.754088	2026-07-16 08:01:36.754089
880dfa4b-f1ae-4938-9182-fc1e39942426	agent	默认任务 Agent	{"tools": ["web_search", "read_doc", "calculate", "get_date", "write_report"], "description": "默认任务执行 Agent，包含当前已接入工具", "modelParams": {"maxTokens": 2000, "temperature": 0.7}, "systemPrompt": "你是一个智能任务执行 Agent。根据用户任务描述，自动规划执行步骤，调用合适的工具完成任务。每次只调用一个工具，根据结果决定下一步。"}	1	t	2026-07-16 08:01:36.763192	2026-07-16 08:01:36.763197
74f449b6-9744-476f-ba04-bf3f0f24a045	workflow	weekly_report	{"icon": "📊", "nodes": [{"id": "extract_highlights", "label": "提炼工作亮点"}, {"id": "identify_risks", "label": "识别风险阻塞"}, {"id": "human_review", "label": "人工审核", "isHuman": true}, {"id": "generate_report", "label": "生成周报"}], "title": "周报生成", "resultKey": "report", "extraField": {"key": "dept", "label": "部门名称", "placeholder": "如：前端研发组"}, "inputLabel": "本周工作要点", "description": "输入本周工作要点，自动提炼亮点、识别风险，生成规范周报", "inputPlaceholder": "请简单描述本周完成的主要工作，一条一行..."}	1	t	2026-07-16 08:01:36.767982	2026-07-16 08:01:36.767986
a8b06ebb-5018-4493-809e-7e5fc92b3f30	workflow	meeting_minutes	{"icon": "📝", "nodes": [{"id": "extract_attendees", "label": "提取参会人与议题"}, {"id": "extract_conclusions", "label": "提取会议结论"}, {"id": "extract_actions", "label": "整理 Action Items"}, {"id": "human_review", "label": "人工审核", "isHuman": true}, {"id": "generate_minutes", "label": "生成纪要"}], "title": "会议纪要", "resultKey": "minutes", "extraField": {"key": "meetingTitle", "label": "会议名称", "placeholder": "如：产品周会 2024-03"}, "inputLabel": "会议原始记录", "description": "粘贴会议原始记录，自动提取结论和 Action Items，生成正式纪要", "inputPlaceholder": "粘贴会议记录，包括讨论内容、发言摘要等..."}	1	t	2026-07-16 08:01:36.76799	2026-07-16 08:01:36.767991
6eac9041-2796-48a9-815f-f050f9ccfa28	workflow	email_polish	{"icon": "✉️", "nodes": [{"id": "analyze_intent", "label": "分析写作意图"}, {"id": "check_issues", "label": "检查问题"}, {"id": "human_review", "label": "人工审核", "isHuman": true}, {"id": "polish_email", "label": "生成润色版本"}], "title": "邮件润色", "resultKey": "polished", "extraField": {"key": "recipient", "label": "收件人/场景", "placeholder": "如：客户、上级、合作方"}, "inputLabel": "邮件草稿", "description": "输入邮件草稿，AI 分析语气和问题，润色成正式邮件", "inputPlaceholder": "粘贴你的邮件草稿..."}	1	t	2026-07-16 08:01:36.767993	2026-07-16 08:01:36.767993
6dce3ed8-495d-40eb-b716-e480e3712d03	workflow	prd_skeleton	{"icon": "📋", "nodes": [{"id": "extract_features", "label": "提取功能点"}, {"id": "identify_constraints", "label": "识别约束条件"}, {"id": "human_review", "label": "人工审核", "isHuman": true}, {"id": "generate_prd", "label": "生成 PRD"}], "title": "PRD 骨架", "resultKey": "prd", "extraField": null, "inputLabel": "需求描述", "description": "输入需求描述，自动提取功能点和约束，生成结构化 PRD 文档", "inputPlaceholder": "用自然语言描述你的产品需求..."}	1	t	2026-07-16 08:01:36.767995	2026-07-16 08:01:36.767996
\.


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: workmind
--

COPY public.alembic_version (version_num) FROM stdin;
003_schema_alignment
\.


--
-- Data for Name: approval_records; Type: TABLE DATA; Schema: public; Owner: workmind
--

COPY public.approval_records (id, session_id, form_type, form_data, flow_json, approvers, status, final_comment, result_json, created_at, completed_at, user_id, request_id) FROM stdin;
976c237d-9e34-4d92-82f4-b7d8ef70a81d	APP_3d04386c88af447b8cb92624fcf98832	leave	{"days": 2.0, "type": "personal", "reason": "T2 SSE disconnect probe", "endDate": "2026-07-23", "workdays": 2.0, "startDate": "2026-07-22", "applicantName": "admin", "emergencyContact": null}	{"approverIds": ["manager", "hr"]}	{"items": [{"id": "manager", "desc": "审核申请合理性，确认业务必要性", "icon": "👔", "name": "直属主管", "color": "#0891b2"}, {"id": "hr", "desc": "审核假期政策合规性，确认余额", "icon": "📋", "name": "HR 专员", "color": "#d97706"}]}	failed	AI 预审执行失败，请稍后重新提交	{"error": "AI 预审执行失败，请稍后重新提交", "messages": [], "simulation": true}	2026-07-16 08:12:55.83058	2026-07-16 08:12:56.21362	admin	t2-sse-f05d8dad2d224d40b9abc66efc505e99
0f1d48b1-4cbf-458a-a79a-e2232ed4a120	APP_b1761f2087ac4f3e98b1a0ee714dede3	leave	{"days": 2.0, "type": "personal", "reason": "T2 idempotency probe t2-erp-c689a3b84e52444ca824c67ee15cbb5b", "endDate": "2026-07-21", "workdays": 2.0, "startDate": "2026-07-20", "applicantName": "admin", "emergencyContact": null}	{"approverIds": ["manager", "hr"]}	{"items": [{"id": "manager", "desc": "审核申请合理性，确认业务必要性", "icon": "👔", "name": "直属主管", "color": "#0891b2"}, {"id": "hr", "desc": "审核假期政策合规性，确认余额", "icon": "📋", "name": "HR 专员", "color": "#d97706"}]}	failed	AI 预审执行失败，请稍后重新提交	{"error": "AI 预审执行失败，请稍后重新提交", "messages": [], "simulation": true}	2026-07-16 08:15:43.816697	2026-07-16 08:15:44.084828	admin	t2-erp-c689a3b84e52444ca824c67ee15cbb5b
b94c5bb9-8576-473e-9443-d5c911ff15b3	APP_8926bb5e8c8d48a2b6a0297107b0691b	leave	{"days": 2.0, "type": "personal", "reason": "T2 idempotency probe", "endDate": "2026-07-21", "workdays": 2.0, "startDate": "2026-07-20", "applicantName": "admin", "emergencyContact": null}	{"approverIds": ["manager", "hr"]}	{"items": [{"id": "manager", "desc": "审核申请合理性，确认业务必要性", "icon": "👔", "name": "直属主管", "color": "#0891b2"}, {"id": "hr", "desc": "审核假期政策合规性，确认余额", "icon": "📋", "name": "HR 专员", "color": "#d97706"}]}	failed	AI 预审执行失败，请稍后重新提交	{"error": "AI 预审执行失败，请稍后重新提交", "messages": [], "simulation": true}	2026-07-16 08:13:17.5245	2026-07-16 08:13:18.042039	admin	t2-erp-943304d88fa74031ab9d84edd7fc5b50
f1abc32b-83cf-4d44-b3a6-098274f5dec7	APP_d210860ec49e4e82bd77dc9488e08c88	leave	{"days": 2.0, "type": "personal", "reason": "T2 SSE disconnect probe t2-sse-092cd31f1a4647f195e24fc9a9b32feb", "endDate": "2026-07-23", "workdays": 2.0, "startDate": "2026-07-22", "applicantName": "admin", "emergencyContact": null}	{"approverIds": ["manager", "hr"]}	{"items": [{"id": "manager", "desc": "审核申请合理性，确认业务必要性", "icon": "👔", "name": "直属主管", "color": "#0891b2"}, {"id": "hr", "desc": "审核假期政策合规性，确认余额", "icon": "📋", "name": "HR 专员", "color": "#d97706"}]}	failed	AI 预审执行失败，请稍后重新提交	{"error": "AI 预审执行失败，请稍后重新提交", "messages": [], "simulation": true}	2026-07-16 08:15:22.086253	2026-07-16 08:15:22.396359	admin	t2-sse-092cd31f1a4647f195e24fc9a9b32feb
768e01b2-0a68-4609-b805-4b638058864a	APP_dfd8fecb62804e98802f4bb0abb4a750	leave	{"days": 2.0, "type": "personal", "reason": "T2 idempotency probe t2-erp-cc9e81015b1b4c638826c3873ff4dbd9", "endDate": "2026-07-21", "workdays": 2.0, "startDate": "2026-07-20", "applicantName": "admin", "emergencyContact": null}	{"approverIds": ["manager", "hr"]}	{"items": [{"id": "manager", "desc": "审核申请合理性，确认业务必要性", "icon": "👔", "name": "直属主管", "color": "#0891b2"}, {"id": "hr", "desc": "审核假期政策合规性，确认余额", "icon": "📋", "name": "HR 专员", "color": "#d97706"}]}	failed	AI 预审执行失败，请稍后重新提交	{"error": "AI 预审执行失败，请稍后重新提交", "messages": [], "simulation": true}	2026-07-16 08:17:32.330143	2026-07-16 08:17:32.571394	admin	t2-erp-cc9e81015b1b4c638826c3873ff4dbd9
943c80fe-8954-44cb-be4e-e1abf5dadba7	APP_46f79a3da0224865ae1d14283dc4f8fb	leave	{"days": 2.0, "type": "personal", "reason": "T2 SSE disconnect probe t2-sse-4ee8012c29144e5f92e30dc3f386ed95", "endDate": "2026-07-23", "workdays": 2.0, "startDate": "2026-07-22", "applicantName": "admin", "emergencyContact": null}	{"approverIds": ["manager", "hr"]}	{"items": [{"id": "manager", "desc": "审核申请合理性，确认业务必要性", "icon": "👔", "name": "直属主管", "color": "#0891b2"}, {"id": "hr", "desc": "审核假期政策合规性，确认余额", "icon": "📋", "name": "HR 专员", "color": "#d97706"}]}	failed	AI 预审执行失败，请稍后重新提交	{"error": "AI 预审执行失败，请稍后重新提交", "messages": [], "simulation": true}	2026-07-16 08:17:10.823111	2026-07-16 08:17:11.076858	admin	t2-sse-4ee8012c29144e5f92e30dc3f386ed95
\.


--
-- Data for Name: conversations; Type: TABLE DATA; Schema: public; Owner: workmind
--

COPY public.conversations (id, session_id, user_id, role, content, model, tokens, metadata, created_at) FROM stdin;
\.


--
-- Data for Name: documents; Type: TABLE DATA; Schema: public; Owner: workmind
--

COPY public.documents (id, title, file_name, category, chunks, chars, preview, created_at, owner_user_id) FROM stdin;
\.


--
-- Data for Name: monitor_records; Type: TABLE DATA; Schema: public; Owner: workmind
--

COPY public.monitor_records (id, "time", feature, input_tokens, output_tokens, cost_usd, cost_cny, latency_ms, from_cache, error) FROM stdin;
1	2026-07-16 08:12:55.864033	erp	0	0	0	0	345.3	f	t
2	2026-07-16 08:13:17.747166	erp	0	0	0	0	288.3	f	t
3	2026-07-16 08:15:43.83116	erp	0	0	0	0	248.9	f	t
4	2026-07-16 08:15:22.136422	erp	0	0	0	0	255.4	f	t
5	2026-07-16 08:17:10.859597	erp	0	0	0	0	211.7	f	t
6	2026-07-16 08:17:32.353634	erp	0	0	0	0	212	f	t
\.


--
-- Data for Name: rag_chunks; Type: TABLE DATA; Schema: public; Owner: workmind
--

COPY public.rag_chunks (id, doc_id, chunk_index, content, embedding, metadata, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: system_settings; Type: TABLE DATA; Schema: public; Owner: workmind
--

COPY public.system_settings (key, value, updated_at) FROM stdin;
daily_budget	{"daily_budget": 1.0}	2026-07-16 08:11:41.15954
\.


--
-- Data for Name: t2_backup_probe; Type: TABLE DATA; Schema: public; Owner: workmind
--

COPY public.t2_backup_probe (id, created_at) FROM stdin;
t2_backup_005b41ca	2026-07-16 08:45:58.872714+00
t2_backup_5a1c5448	2026-07-16 08:49:29.030202+00
t2_backup_e138dada	2026-07-16 08:50:27.912496+00
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: workmind
--

COPY public.users (id, username, password_hash, role, created_at, is_active) FROM stdin;
admin	admin	$2b$12$rkH9lvn2wS/7hKN2nyd1bOf5.aQq63XSMgntV1VQe3hwL0GFCE9dW	admin	2026-07-16 08:01:37.211305	t
user	user	$2b$12$LSol7KfjpMdD/KJiAC7.Auk8q0OwqJqzMeMSEwDvdJK6CD1p.gjkO	user	2026-07-16 08:01:37.211312	t
\.


--
-- Name: monitor_records_id_seq; Type: SEQUENCE SET; Schema: public; Owner: workmind
--

SELECT pg_catalog.setval('public.monitor_records_id_seq', 6, true);


--
-- Name: agent_configs agent_configs_name_key; Type: CONSTRAINT; Schema: public; Owner: workmind
--

ALTER TABLE ONLY public.agent_configs
    ADD CONSTRAINT agent_configs_name_key UNIQUE (name);


--
-- Name: agent_configs agent_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: workmind
--

ALTER TABLE ONLY public.agent_configs
    ADD CONSTRAINT agent_configs_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: workmind
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: approval_records approval_records_pkey; Type: CONSTRAINT; Schema: public; Owner: workmind
--

ALTER TABLE ONLY public.approval_records
    ADD CONSTRAINT approval_records_pkey PRIMARY KEY (id);


--
-- Name: conversations conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: workmind
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_pkey PRIMARY KEY (id);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: workmind
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);


--
-- Name: monitor_records monitor_records_pkey; Type: CONSTRAINT; Schema: public; Owner: workmind
--

ALTER TABLE ONLY public.monitor_records
    ADD CONSTRAINT monitor_records_pkey PRIMARY KEY (id);


--
-- Name: rag_chunks rag_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: workmind
--

ALTER TABLE ONLY public.rag_chunks
    ADD CONSTRAINT rag_chunks_pkey PRIMARY KEY (id);


--
-- Name: system_settings system_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: workmind
--

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT system_settings_pkey PRIMARY KEY (key);


--
-- Name: t2_backup_probe t2_backup_probe_pkey; Type: CONSTRAINT; Schema: public; Owner: workmind
--

ALTER TABLE ONLY public.t2_backup_probe
    ADD CONSTRAINT t2_backup_probe_pkey PRIMARY KEY (id);


--
-- Name: rag_chunks uq_rag_chunks_doc_chunk; Type: CONSTRAINT; Schema: public; Owner: workmind
--

ALTER TABLE ONLY public.rag_chunks
    ADD CONSTRAINT uq_rag_chunks_doc_chunk UNIQUE (doc_id, chunk_index);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: workmind
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: workmind
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: idx_agent_configs_active; Type: INDEX; Schema: public; Owner: workmind
--

CREATE INDEX idx_agent_configs_active ON public.agent_configs USING btree (is_active);


--
-- Name: idx_agent_configs_type; Type: INDEX; Schema: public; Owner: workmind
--

CREATE INDEX idx_agent_configs_type ON public.agent_configs USING btree (config_type);


--
-- Name: idx_approval_session; Type: INDEX; Schema: public; Owner: workmind
--

CREATE UNIQUE INDEX idx_approval_session ON public.approval_records USING btree (session_id);


--
-- Name: idx_approval_status; Type: INDEX; Schema: public; Owner: workmind
--

CREATE INDEX idx_approval_status ON public.approval_records USING btree (status);


--
-- Name: idx_approval_user_created; Type: INDEX; Schema: public; Owner: workmind
--

CREATE INDEX idx_approval_user_created ON public.approval_records USING btree (user_id, created_at);


--
-- Name: idx_conversations_session; Type: INDEX; Schema: public; Owner: workmind
--

CREATE INDEX idx_conversations_session ON public.conversations USING btree (session_id, created_at);


--
-- Name: idx_documents_owner_created; Type: INDEX; Schema: public; Owner: workmind
--

CREATE INDEX idx_documents_owner_created ON public.documents USING btree (owner_user_id, created_at);


--
-- Name: idx_monitor_records_feature; Type: INDEX; Schema: public; Owner: workmind
--

CREATE INDEX idx_monitor_records_feature ON public.monitor_records USING btree (feature);


--
-- Name: idx_monitor_records_time; Type: INDEX; Schema: public; Owner: workmind
--

CREATE INDEX idx_monitor_records_time ON public.monitor_records USING btree ("time");


--
-- Name: idx_rag_chunks_doc_id; Type: INDEX; Schema: public; Owner: workmind
--

CREATE INDEX idx_rag_chunks_doc_id ON public.rag_chunks USING btree (doc_id);


--
-- Name: idx_rag_chunks_embedding_hnsw; Type: INDEX; Schema: public; Owner: workmind
--

CREATE INDEX idx_rag_chunks_embedding_hnsw ON public.rag_chunks USING hnsw (embedding public.vector_cosine_ops) WHERE (embedding IS NOT NULL);


--
-- Name: ix_conversations_user_id; Type: INDEX; Schema: public; Owner: workmind
--

CREATE INDEX ix_conversations_user_id ON public.conversations USING btree (user_id);


--
-- Name: uq_approval_user_request; Type: INDEX; Schema: public; Owner: workmind
--

CREATE UNIQUE INDEX uq_approval_user_request ON public.approval_records USING btree (user_id, request_id) WHERE (request_id IS NOT NULL);


--
-- Name: documents fk_documents_owner; Type: FK CONSTRAINT; Schema: public; Owner: workmind
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT fk_documents_owner FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: rag_chunks fk_rag_chunks_document; Type: FK CONSTRAINT; Schema: public; Owner: workmind
--

ALTER TABLE ONLY public.rag_chunks
    ADD CONSTRAINT fk_rag_chunks_document FOREIGN KEY (doc_id) REFERENCES public.documents(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict GnTO4YPeLyDkl5nWCzHm2mp4EGIUv2Xt3gcWhFTVhsYHr02dGXZwUzGBR4k2cWG

