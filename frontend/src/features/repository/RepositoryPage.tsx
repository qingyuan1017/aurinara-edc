import {
  type ChangeEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Archive,
  Download,
  Eye,
  File,
  Folder,
  FolderPlus,
  RefreshCw,
  Search,
  Share2,
  Upload,
  X,
} from "lucide-react";
import { RepositoryPreview } from "@/components/repository-preview";
import { api } from "@/lib/api";
import {
  repositoryApi,
  uploadRepositoryFile,
  waitForRepositoryJob,
  type RepositoryNode,
  type RepositoryVersion,
  type UploadProgress,
} from "@/lib/repository-client";

export function RepositoryPage({ studyId }: { studyId: string }) {
  const [query, setQuery] = useState("");
  const [view, setView] = useState("folder");
  const [path, setPath] = useState<RepositoryNode[]>([]);
  const [items, setItems] = useState<RepositoryNode[]>([]);
  const [folders, setFolders] = useState<RepositoryNode[]>([]);
  const [selected, setSelected] = useState<RepositoryNode | null>(null);
  const [versions, setVersions] = useState<RepositoryVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [preview, setPreview] = useState(false);
  const [caps, setCaps] = useState({
    can_upload: false,
    can_create_folder: false,
  });
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | undefined>(undefined);
  const deepNodeId = useRef<string | null>(null);
  const currentFolder = path.at(-1) ?? null;

  useEffect(() => {
    if (!preview) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreview(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [preview]);

  const load = useCallback(async () => {
    setLoading(true);
    setNotice("");
    try {
      const params = new URLSearchParams({ view, limit: "100" });
      if (query.trim()) params.set("q", query.trim());
      if (view === "folder" && currentFolder)
        params.set("parent_id", currentFolder.id);
      const [page, all] = await Promise.all([
        repositoryApi.browse(studyId, params),
        repositoryApi.browse(
          studyId,
          new URLSearchParams({ view: "all", limit: "100" }),
        ),
      ]);
      setItems(page.items);
      setCaps(page.capabilities);
      setFolders(
        all.items.filter(
          (item) =>
            item.kind === "folder" && item.lifecycle_status === "active",
        ),
      );
      setSelected(
        (value) =>
          page.items.find((item) => item.id === value?.id) ??
          (value?.id === deepNodeId.current ? value : null),
      );
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Repository unavailable",
      );
    } finally {
      setLoading(false);
    }
  }, [studyId, query, view, currentFolder]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setPath([]);
      setSelected(null);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [studyId]);
  useEffect(() => {
    const parameters = new URLSearchParams(location.search);
    const linkedVersion = parameters.get("version");
    const linkedStudy = parameters.get("study");
    if (!linkedVersion) return;
    void repositoryApi
      .version(linkedVersion)
      .then(async (binding) => {
        if (
          binding.study_id !== studyId ||
          (linkedStudy && linkedStudy !== studyId)
        )
          throw new Error("The deep link belongs to another study");
        deepNodeId.current = binding.node_id;
        setSelected(await repositoryApi.node(binding.node_id));
        setPreview(true);
      })
      .catch((error) =>
        setNotice(
          error instanceof Error ? error.message : "Deep link unavailable",
        ),
      );
  }, [studyId]);
  useEffect(() => {
    if (!selected || selected.kind !== "file") return;
    void repositoryApi
      .versions(selected.id)
      .then((values) => {
        setVersions(values);
        const linked = new URLSearchParams(location.search).get("version");
        if (linked && !values.some((value) => value.id === linked))
          setNotice("The linked version is unavailable or unauthorized.");
      })
      .catch((error) =>
        setNotice(
          error instanceof Error ? error.message : "Version unavailable",
        ),
      );
  }, [selected]);

  const destinations = useMemo(
    () =>
      folders.filter(
        (folder) =>
          selected &&
          folder.id !== selected.id &&
          folder.source_product === selected.source_product &&
          folder.required_read_action === selected.required_read_action &&
          folder.required_write_action === selected.required_write_action &&
          folder.site_id === selected.site_id,
      ),
    [folders, selected],
  );
  const download = async (version = versions[0]) => {
    if (!version) return;
    const result = await repositoryApi.download(version.id);
    window.open(result.url, "_blank", "noopener,noreferrer");
  };
  const attach = async () => {
    if (!versions[0]) return;
    try {
      await api.post(`/studies/${studyId}/repository/attachments:bind`, {
        version_id: versions[0].id,
        expected_sha256: versions[0].sha256,
      });
      setNotice("Repository version attached to this study.");
    } catch {
      setNotice("Could not attach this Repository version.");
    }
  };
  const createFolder = async () => {
    const name = prompt("Folder name")?.trim();
    if (!name) return;
    try {
      await repositoryApi.folder(studyId, name, currentFolder?.id || null);
      await load();
    } catch (error) {
      setNotice(String(error));
    }
  };
  const rename = async () => {
    if (!selected) return;
    const name = prompt("New name", selected.display_name)?.trim();
    if (!name) return;
    try {
      setSelected(await repositoryApi.patch(selected, { name }));
      await load();
    } catch (error) {
      setNotice(String(error));
    }
  };
  const move = async (parentId: string) => {
    if (!selected) return;
    try {
      setSelected(
        await repositoryApi.patch(selected, { parent_id: parentId || null }),
      );
      await load();
    } catch (error) {
      setNotice(String(error));
    }
  };
  const archive = async () => {
    if (!selected) return;
    try {
      setSelected(
        selected.lifecycle_status === "archived"
          ? await repositoryApi.restore(selected)
          : await repositoryApi.archive(selected),
      );
      await load();
    } catch (error) {
      setNotice(String(error));
    }
  };
  const upload = async (
    event: ChangeEvent<HTMLInputElement>,
    replacement: RepositoryNode | null = null,
  ) => {
    const file = event.target.files?.[0];
    if (!file) return;
    abort.current = new AbortController();
    try {
      await uploadRepositoryFile(
        studyId,
        file,
        currentFolder?.id || null,
        replacement,
        setProgress,
        abort.current.signal,
      );
      setNotice(
        replacement ? "New immutable version added." : "File uploaded.",
      );
      await load();
      if (replacement)
        setVersions(await repositoryApi.versions(replacement.id));
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError"))
        setNotice(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setProgress(null);
      event.target.value = "";
    }
  };
  const convert = async (target: "csv" | "parquet") => {
    if (!selected || !versions[0]) return;
    const filename = prompt(
      "Output filename",
      `${selected.display_name.replace(/\.[^.]+$/, "")}.${target}`,
    )?.trim();
    if (!filename) return;
    try {
      const job = await repositoryApi.convert(versions[0].id, target, filename);
      setNotice("Conversion queued.");
      await waitForRepositoryJob(job);
      setNotice("Conversion completed.");
      await load();
    } catch (error) {
      setNotice(String(error));
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Repository</h1>
        <p className="text-sm text-muted-foreground">
          One authorized file experience across Platform, Aurinara, EDC, CTMS,
          and PV.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <label className="relative min-w-64 flex-1">
          <Search className="absolute left-3 top-2.5 size-4 text-muted-foreground" />
          <input
            className="h-9 w-full rounded-md border bg-background pl-9 text-sm"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search files"
          />
        </label>
        <select
          className="h-9 rounded-md border bg-background px-3 text-sm"
          value={view}
          onChange={(event) => {
            setView(event.target.value);
            setPath([]);
            setSelected(null);
          }}
        >
          <option value="folder">Folders</option>
          <option value="all">All files</option>
          <option value="recent">Recent</option>
          <option value="aurinara">Aurinara</option>
          <option value="aurinara-edc">EDC / CTMS / PV</option>
          <option value="platform">Neutral</option>
          <option value="archived">Archived</option>
        </select>
        <button
          className="inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm disabled:opacity-50"
          disabled={!caps.can_create_folder}
          onClick={() => void createFolder()}
        >
          <FolderPlus className="size-4" />
          Folder
        </button>
        <button
          className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm text-primary-foreground disabled:opacity-50"
          disabled={!caps.can_upload}
          onClick={() => input.current?.click()}
        >
          <Upload className="size-4" />
          Upload
        </button>
        <input
          ref={input}
          hidden
          type="file"
          onChange={(event) => void upload(event)}
        />
        <button
          className="rounded-md border px-3"
          onClick={() => void load()}
          aria-label="Refresh"
        >
          <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
        </button>
        {progress && (
          <span className="self-center text-xs">
            {progress.phase}{" "}
            {Math.round((progress.loaded / Math.max(1, progress.total)) * 100)}%{" "}
            <button
              className="underline"
              onClick={() => abort.current?.abort()}
            >
              Cancel
            </button>
          </span>
        )}
      </div>
      {view === "folder" && (
        <nav
          className="flex flex-wrap items-center gap-1 text-sm"
          aria-label="Repository folders"
        >
          <button
            className="rounded px-2 py-1 text-primary hover:bg-muted"
            onClick={() => {
              setPath([]);
              setSelected(null);
            }}
          >
            Repository
          </button>
          {path.map((folder, index) => (
            <span key={folder.id}>
              {" "}
              /{" "}
              <button
                className="rounded px-2 py-1 text-primary hover:bg-muted"
                onClick={() => setPath(path.slice(0, index + 1))}
              >
                {folder.display_name}
              </button>
            </span>
          ))}
        </nav>
      )}
      {notice && (
        <p className="rounded-md border bg-muted p-3 text-sm">{notice}</p>
      )}
      <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
        <section className="overflow-hidden rounded-xl border bg-card">
          {items.map((item) => (
            <button
              key={item.id}
              className={`grid w-full grid-cols-[1fr_110px_100px] items-center border-b px-4 py-3 text-left text-sm hover:bg-muted/50 ${selected?.id === item.id ? "bg-muted" : ""}`}
              onClick={() => setSelected(item)}
              onDoubleClick={() =>
                item.kind === "folder" &&
                (setPath([...path, item]), setView("folder"), setSelected(null))
              }
            >
              <span className="flex min-w-0 items-center gap-2">
                {item.kind === "folder" ? (
                  <Folder className="size-4 text-amber-500" />
                ) : (
                  <File className="size-4 text-primary" />
                )}
                <span className="truncate">{item.display_name}</span>
              </span>
              <span className="truncate text-xs text-muted-foreground">
                {item.source_product}
              </span>
              <span className="text-xs text-muted-foreground">
                {item.lifecycle_status === "archived"
                  ? "archived"
                  : item.source_status}
              </span>
            </button>
          ))}
          {!loading && !items.length && (
            <p className="p-12 text-center text-sm text-muted-foreground">
              No authorized files found.
            </p>
          )}
        </section>
        <aside className="space-y-4 rounded-xl border bg-card p-5">
          <div>
            <h2 className="font-semibold">
              {selected?.display_name ?? "File details"}
            </h2>
            <p className="text-xs text-muted-foreground">
              {selected
                ? `${selected.source_product} · ${selected.classification}`
                : "Select a file"}
            </p>
          </div>
          {selected && (
            <>
              <div className="flex flex-wrap gap-2">
                {selected.capabilities.can_manage && (
                  <button
                    className="h-9 rounded-md border px-3 text-sm"
                    onClick={() => void rename()}
                  >
                    Rename
                  </button>
                )}
                {selected.kind === "file" && (
                  <button
                    className="inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm"
                    onClick={() => void download()}
                  >
                    <Download className="size-4" />
                    Download
                  </button>
                )}
                {selected.capabilities.can_preview && (
                  <button
                    className="inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm"
                    onClick={() => setPreview(true)}
                  >
                    <Eye className="size-4" />
                    Open preview
                  </button>
                )}
                {selected.kind === "file" && (
                  <button
                    className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm text-primary-foreground"
                    onClick={() => void attach()}
                  >
                    <Share2 className="size-4" />
                    Attach
                  </button>
                )}
                {selected.capabilities.can_manage && (
                  <button
                    className="inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm"
                    onClick={() => void archive()}
                  >
                    <Archive className="size-4" />
                    {selected.lifecycle_status === "archived"
                      ? "Restore"
                      : "Archive"}
                  </button>
                )}
              </div>
              {selected.capabilities.can_manage && (
                <select
                  className="h-9 w-full rounded-md border bg-background px-2 text-sm"
                  value={selected.parent_id || ""}
                  onChange={(event) => void move(event.target.value)}
                >
                  <option value="">Repository root</option>
                  {destinations.map((folder) => (
                    <option key={folder.id} value={folder.id}>
                      {folder.display_name}
                    </option>
                  ))}
                </select>
              )}
              {selected.kind === "file" && selected.capabilities.can_manage && (
                <label className="block cursor-pointer rounded-md border p-2 text-center text-sm">
                  <Upload className="mr-2 inline size-4" />
                  New version
                  <input
                    hidden
                    type="file"
                    onChange={(event) => void upload(event, selected)}
                  />
                </label>
              )}
              {versions[0]?.capabilities.conversion_targets.map((target) => (
                <button
                  key={target}
                  className="h-9 rounded-md border px-3 text-sm"
                  onClick={() => void convert(target)}
                >
                  Convert to {target.toUpperCase()}
                </button>
              ))}
              <div className="space-y-2">
                {versions.map((version) => (
                  <button
                    key={version.id}
                    className="block w-full rounded-md bg-muted p-3 text-left text-xs"
                    onClick={() => void download(version)}
                  >
                    <strong>v{version.version_number}</strong>
                    <p className="text-muted-foreground">
                      {version.profile?.file_kind || version.media_type} ·{" "}
                      {version.profile?.processing_status || "pending"} ·{" "}
                      {(version.size_bytes / 1024).toFixed(1)} KB
                    </p>
                  </button>
                ))}
              </div>
            </>
          )}
        </aside>
      </div>
      {preview && selected?.kind === "file" && versions[0] && (
        <div
          className="fixed inset-0 z-[100] grid place-items-center bg-slate-950/75 p-3 backdrop-blur-sm md:p-8"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setPreview(false);
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-label={`Preview ${selected.display_name}`}
            className="grid h-full w-full max-w-[1600px] grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-2xl border bg-background shadow-2xl"
          >
            <header className="flex items-center justify-between gap-4 border-b bg-card px-4 py-3 md:px-6">
              <div className="flex min-w-0 items-center gap-3">
                <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
                  <File className="size-5" />
                </span>
                <div className="min-w-0">
                  <p className="text-[11px] font-semibold tracking-wider text-muted-foreground uppercase">
                    {versions[0].profile?.file_kind || "file"} · Version {versions[0].version_number}
                  </p>
                  <h2 className="truncate text-base font-semibold md:text-lg">
                    {selected.display_name}
                  </h2>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span className="hidden rounded-full bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-700 sm:inline">
                  {versions[0].profile?.processing_status || "pending"}
                </span>
                <button className="inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm" onClick={() => void download(versions[0])}>
                  <Download className="size-4" />
                  <span className="hidden sm:inline">Download</span>
                </button>
                <button className="grid size-9 place-items-center rounded-md border" aria-label="Close preview" onClick={() => setPreview(false)}>
                  <X className="size-4" />
                </button>
              </div>
            </header>
            <div className="min-h-0 overflow-auto bg-muted/30 p-3 md:p-5">
              <RepositoryPreview
                node={selected}
                version={versions[0]}
                changed={() => void load()}
              />
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
