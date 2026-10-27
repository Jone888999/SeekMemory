import { PackPreview } from "./pack-preview"
import { personaBlueprint, packInstallLabel } from "../model"
import type { ArtifactDetail } from "@/features/control/model"
import { useCallback, useEffect, useRef, useState } from "react"
import { ArrowUpRight, Plus, Search } from "lucide-react"
import { Badge, Button, Input } from "@/ui"
import avatar from "@/assets/ds-chibi-head.webp"
import {
  seedSchema,
  type PersonaPack,
  type PersonaSeed,
  type ConsoleClient,
} from "@/features/shell/model"
import type { RuntimeStatus } from "@/features/control/model"
import { useResource } from "@/features/shell/use-resource"
import { PageIntro, ResourceState } from "@/features/shell/page-parts"

export function StorePage({
  client,
  status,
  onSaved,
  readPersona,
}: {
  client: ConsoleClient
  status: RuntimeStatus | null
  readPersona: (id: string) => Promise<ArtifactDetail>
  onSaved: () => Promise<void>
}) {
  const [collection, setCollection] = useState<"official" | "mine">("official")
  const [offset, setOffset] = useState(0),
    [query, setQuery] = useState("")
  const [installBase, setInstallBase] = useState<{
    id: string | null
    revision: number
  }>({ id: null, revision: 0 })
  const [selected, setSelected] = useState<PersonaPack | null>(null)
  const [digest, setDigest] = useState("")
  const [seed, setSeed] = useState<PersonaSeed | null>(null)
  const [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false)
  const [error, setError] = useState(""),
    [notice, setNotice] = useState("")
  const [chatImport, setChatImport] = useState(false)
  const [pendingImport, setPendingImport] = useState<PersonaSeed | null>(null)
  const [expectedVersion, setExpectedVersion] = useState("")
  const [removeConfirmed, setRemoveConfirmed] = useState(false)
  const [saveName, setSaveName] = useState("")
  const request = useRef(0),
    acting = useRef(false)
  useEffect(
    () => () => {
      request.current++
    },
    []
  )
  const read = useCallback(
    () => client.packs(collection, offset),
    [client, collection, offset]
  )
  const vm = useResource(read)
  const preview = async (pack: PersonaPack) => {
    const version = ++request.current
    setInstallBase({
      id: status?.persona?.id ?? null,
      revision: status?.persona?.revision ?? 0,
    })
    setSelected(pack)
    setSeed(null)
    setDigest("")
    setError("")
    setConfirmed(false)
    setRemoveConfirmed(false)
    try {
      const result = await client.pack(pack.reference)
      if (version === request.current) {
        setSeed(result.seed)
        setDigest(result.digest)
      }
    } catch (e) {
      if (version === request.current)
        setError(e instanceof Error ? e.message : "读取失败")
    }
  }
  const mutate = async (operation: () => Promise<unknown>, success: string) => {
    if (acting.current) return false
    acting.current = true
    setBusy(true)
    setError("")
    setNotice("")
    try {
      await operation()
      setNotice(success)
      setSelected(null)
      setSeed(null)
      setConfirmed(false)
      await Promise.all([vm.reload(), onSaved()])
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败")
      return false
    } finally {
      acting.current = false
      setBusy(false)
    }
  }
  const importFile = async (file: File | undefined) => {
    if (!file) return
    try {
      if (file.size > 65536) throw new Error("人格文件不能超过 64 KB")
      const value: unknown = JSON.parse(await file.text())
      const imported = seedSchema.parse(value)
      setPendingImport(imported)
      setExpectedVersion(
        vm.data?.items.find((p) => p.id === imported.id)?.version ?? ""
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : "文件格式无效")
    }
  }
  const items =
    vm.data?.items.filter((pack) =>
      `${pack.name} ${pack.description}`
        .toLowerCase()
        .includes(query.toLowerCase())
    ) ?? []
  return (
    <div className="console-page console-store">
      <PageIntro title="人格小铺" />
      <div className="store-tabs">
        <Button
          variant={collection === "official" ? "default" : "ghost"}
          onClick={() => {
            setChatImport(false)
            setCollection("official")
            setOffset(0)
          }}
        >
          官方种子
        </Button>
        <Button
          variant={collection === "mine" ? "default" : "ghost"}
          onClick={() => {
            setChatImport(false)
            setCollection("mine")
            setOffset(0)
          }}
        >
          我的包
        </Button>
        <Button
          variant={chatImport ? "default" : "ghost"}
          onClick={() => setChatImport(true)}
        >
          导入聊天
        </Button>
      </div>
      {chatImport ? (
        <div className="console-empty">
          <h2>从真实相处中塑造人格</h2>
          <p>聊天导入会保存真实对话，再由记忆整理逐步形成印象和人格。</p>
          <Button disabled>聊天导入暂未开放</Button>
        </div>
      ) : (
        <>
          <div className="console-toolbar">
            <Search size={16} />
            <Input
              aria-label="搜索当前页人格包"
              placeholder="搜索当前页的人格…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="max-w-sm"
            />
            <span className="ml-auto text-xs text-muted-foreground">
              {vm.data?.total ?? 0} 个人格包
            </span>
          </div>
          {collection === "mine" && (
            <section className="console-panel mb-6 space-y-4 p-5">
              <div className="flex flex-wrap items-center gap-3">
                <label className="console-upload">
                  <Plus size={15} />
                  导入人格 JSON
                  <input
                    type="file"
                    accept=".json,application/json"
                    disabled={busy}
                    onChange={(e) => {
                      void importFile(e.target.files?.[0])
                      e.target.value = ""
                    }}
                  />
                </label>
                <p className="text-xs text-muted-foreground">
                  仅导入设定文件；不会导入聊天，也不会自动安装。
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <Input
                  aria-label="保存当前人格的包名称"
                  placeholder="为当前人格取一个包名"
                  value={saveName}
                  onChange={(e) => setSaveName(e.target.value)}
                  className="max-w-sm"
                />
                <Button
                  variant="outline"
                  disabled={busy || !status?.persona || !saveName.trim()}
                  onClick={() => {
                    if (!status?.persona) return
                    const id = status.persona.id
                    void mutate(async () => {
                      const detail = await readPersona(id)
                      const current = personaBlueprint(
                        detail,
                        saveName.trim(),
                        `my-${crypto.randomUUID().slice(0, 12)}`
                      )
                      return client.persona({
                        operation: "import",
                        seed: current,
                        confirmed: true,
                      })
                    }, "已保存人格蓝图，不包含聊天来源或证据。")
                  }}
                >
                  保存当前人格为包
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                保存人格文字、风格和边界，不复制聊天、来源或私人证据。分享前请自行检查人格文字。
              </p>
            </section>
          )}
          {error && (
            <p role="alert" className="my-4 text-sm text-destructive">
              {error}
            </p>
          )}
          {notice && (
            <p role="status" className="my-4 text-sm text-success">
              {notice}
            </p>
          )}
          <ResourceState
            loading={vm.loading}
            error={vm.error}
            empty={!!vm.data && !items.length}
            onRetry={vm.reload}
          />
          <div className="store-grid">
            {items.map((pack) => (
              <button
                className="console-panel seed-card"
                key={pack.reference}
                onClick={() => {
                  void preview(pack)
                }}
              >
                <div
                  className={`seed-art ${pack.id === "big_fish" ? "seed-art-fish" : "seed-art-neutral"}`}
                >
                  {pack.id === "big_fish" ? (
                    <img src={avatar} alt="蓝发 Q 版角色趴桌头像" />
                  ) : (
                    <span aria-hidden="true">{pack.name.slice(0, 1)}</span>
                  )}
                  <Badge variant="outline">
                    {pack.contentRating === "general"
                      ? "全年龄"
                      : pack.contentRating}
                  </Badge>
                </div>
                <div className="p-5 text-left">
                  <div className="flex justify-between">
                    <h2 className="text-lg font-semibold">{pack.name}</h2>
                    <ArrowUpRight size={17} />
                  </div>
                  <p className="my-3 line-clamp-2 text-sm leading-6 text-muted-foreground">
                    {pack.description}
                  </p>
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>{pack.license || "许可未声明"}</span>
                    <span>
                      v{pack.version}
                      {packInstallLabel(pack, status?.persona)}
                    </span>
                  </div>
                </div>
              </button>
            ))}
          </div>
          {vm.data && vm.data.total > 24 && (
            <div className="console-toolbar mt-5">
              <Button
                disabled={!offset}
                onClick={() => setOffset(Math.max(0, offset - 24))}
              >
                上一页
              </Button>
              <Button
                disabled={offset + 24 >= vm.data.total}
                onClick={() => setOffset(offset + 24)}
              >
                下一页
              </Button>
            </div>
          )}
        </>
      )}
      {pendingImport && (
        <section className="console-panel my-5 space-y-4 p-6">
          <h2>
            确认导入：{pendingImport.name} · v{pendingImport.version}
          </h2>
          <p className="text-sm text-muted-foreground">
            {pendingImport.persona.slice(0, 160)}
          </p>
          <Input
            aria-label="被更新人格包的旧版本"
            placeholder="新增包请留空；更新同名包请填写旧版本号"
            value={expectedVersion}
            onChange={(e) => setExpectedVersion(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            更新仅替换本地蓝图，保留旧文件备份；需要再次安装才能改变当前人格。
          </p>
          <Button
            disabled={busy}
            onClick={() => {
              void mutate(
                () =>
                  client.persona({
                    operation: "import",
                    seed: pendingImport,
                    confirmed: true,
                    ...(expectedVersion ? { expectedVersion } : {}),
                  }),
                "人格蓝图已保存，当前人格未改变。"
              ).then((saved) => {
                if (saved) setPendingImport(null)
              })
            }}
          >
            确认保存蓝图
          </Button>
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => setPendingImport(null)}
          >
            取消
          </Button>
        </section>
      )}
      <PackPreview
        selected={selected}
        seed={seed}
        error={error}
        busy={busy}
        status={status}
        confirmed={confirmed}
        setConfirmed={setConfirmed}
        removeConfirmed={removeConfirmed}
        setRemoveConfirmed={setRemoveConfirmed}
        onClose={() => {
          request.current++
          setSelected(null)
          setSeed(null)
        }}
        onInstall={() => {
          if (selected)
            void mutate(
              () =>
                client.persona({
                  operation: "install",
                  reference: selected.reference,
                  expectedId: installBase.id,
                  expectedRevision: installBase.revision,
                  expectedDigest: digest,
                  confirmed: true,
                }),
              "人格已安装，首页已更新。"
            )
        }}
        onRemove={() => {
          if (selected)
            void mutate(
              () =>
                client.persona({
                  operation: "remove",
                  reference: selected.reference,
                  confirmed: true,
                }),
              "已移入本地回收目录；当前人格未改变。"
            )
        }}
      />
    </div>
  )
}
