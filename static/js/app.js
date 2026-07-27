/**
 * Vue 3 root application for Git Commit Integrator
 */
const { createApp, ref, reactive, computed, watch, nextTick, onMounted } = Vue;
const api = window.GitIntegratorAPI;
const utils = window.GitIntegratorUtils;

const App = {
  setup() {
    const loading = reactive({
      repo: false,
      branches: false,
      authors: false,
      commits: false,
      stats: false,
      integrate: false,
      preview: false,
      restore: false,
    });

    const repoPath = ref("");
    const repoConfigured = ref(false);
    const currentBranch = ref("");
    const repoClean = ref(true);

    const branches = ref([]);
    const sourceBranch = ref("");
    const targetBranch = ref("");

    const authors = ref([]);
    const filters = reactive({
      authors: [],
      types: [],
      dateRange: null,
      keyword: "",
    });

    const commits = ref([]);
    const total = ref(0);
    const page = ref(1);
    const pageSize = ref(20);
    const sortBy = ref("date");
    const sortOrder = ref("desc");
    const selectedHashes = ref([]);

    const stats = reactive({
      total_commits: 0,
      selected_count: 0,
      author_count: 0,
      additions: 0,
      deletions: 0,
    });

    const integrateMode = ref("normal");
    const conflictStrategy = ref("pause");
    const squashMessage = ref("");

    const progress = ref(0);
    const progressText = ref("");
    const logs = ref([]);
    const logBox = ref(null);
    const eventSource = ref(null);
    const currentJobId = ref("");

    const lastBackup = reactive({
      branch: "",
      restoreCommand: "",
      target: "",
    });

    const detailVisible = ref(false);
    const detailLoading = ref(false);
    const detail = ref(null);

    const helpVisible = ref(false);
    const previewVisible = ref(false);
    const previewResult = ref(null);
    const reportVisible = ref(false);
    const report = ref(null);

    const typeOptions = utils.COMMIT_TYPES;

    const selectedCount = computed(() => selectedHashes.value.length);

    function appendLog(message, level = "info") {
      logs.value.push({
        time: utils.formatNow(),
        level,
        message,
      });
      nextTick(() => {
        if (logBox.value) {
          logBox.value.scrollTop = logBox.value.scrollHeight;
        }
      });
    }

    function clearLogs() {
      logs.value = [];
      progress.value = 0;
      progressText.value = "";
    }

    async function withError(fn, loadingKey) {
      if (loadingKey) loading[loadingKey] = true;
      try {
        return await fn();
      } catch (err) {
        const msg = err.message || String(err);
        ElementPlus.ElMessage.error(err.detail ? `${msg}: ${err.detail}` : msg);
        appendLog(err.detail ? `${msg} — ${err.detail}` : msg, "error");
        throw err;
      } finally {
        if (loadingKey) loading[loadingKey] = false;
      }
    }

    async function loadRepo() {
      await withError(async () => {
        const data = await api.getRepo();
        repoConfigured.value = !!data.configured;
        repoPath.value = data.path || "";
        currentBranch.value = data.current_branch || "";
        repoClean.value = data.clean !== false;
        if (repoConfigured.value) {
          await loadBranches();
        }
      }, "repo");
    }

    async function applyRepoPath() {
      if (!repoPath.value.trim()) {
        ElementPlus.ElMessage.warning("请输入仓库路径");
        return;
      }
      await withError(async () => {
        const data = await api.setRepo(repoPath.value.trim());
        repoConfigured.value = true;
        repoPath.value = data.path;
        currentBranch.value = data.current_branch || "";
        repoClean.value = data.clean !== false;
        selectedHashes.value = [];
        clearLogs();
        appendLog(`已切换仓库: ${data.path}`, "info");
        ElementPlus.ElMessage.success("仓库已设置");
        await loadBranches();
      }, "repo");
    }

    async function loadBranches() {
      await withError(async () => {
        const data = await api.getBranches();
        branches.value = data.branches || [];
        currentBranch.value = data.current || "";
        if (!sourceBranch.value || !branches.value.includes(sourceBranch.value)) {
          sourceBranch.value = branches.value.find((b) => b !== data.current) || data.current || "";
        }
        if (!targetBranch.value || !branches.value.includes(targetBranch.value)) {
          targetBranch.value = data.current || "";
        }
        if (sourceBranch.value) {
          await loadAuthors();
          await loadCommits();
        }
      }, "branches");
    }

    async function loadAuthors() {
      if (!sourceBranch.value) return;
      await withError(async () => {
        authors.value = await api.getAuthors(sourceBranch.value);
      }, "authors");
    }

    async function loadCommits() {
      if (!sourceBranch.value) return;
      await withError(async () => {
        const params = {
          source: sourceBranch.value,
          author: filters.authors,
          type: filters.types,
          keyword: filters.keyword,
          sort_by: sortBy.value,
          sort_order: sortOrder.value,
          page: page.value,
          page_size: pageSize.value,
        };
        if (filters.dateRange && filters.dateRange.length === 2) {
          params.date_from = filters.dateRange[0];
          params.date_to = filters.dateRange[1];
        }
        const data = await api.getCommits(params);
        commits.value = data.items || [];
        total.value = data.total || 0;
        await refreshStats();
      }, "commits");
    }

    async function refreshStats() {
      await withError(async () => {
        const data = await api.getStats({
          source: sourceBranch.value,
          hashes: selectedHashes.value,
        });
        stats.total_commits = data.total_commits || total.value;
        stats.selected_count = data.selected_count || 0;
        stats.author_count = data.author_count || 0;
        stats.additions = data.additions || 0;
        stats.deletions = data.deletions || 0;
      }, "stats");
    }

    function applyFilters() {
      page.value = 1;
      loadCommits();
    }

    function resetFilters() {
      filters.authors = [];
      filters.types = [];
      filters.dateRange = null;
      filters.keyword = "";
      page.value = 1;
      sortBy.value = "date";
      sortOrder.value = "desc";
      loadCommits();
    }

    const debouncedKeywordSearch = utils.debounce(() => {
      page.value = 1;
      loadCommits();
    }, 300);

    function onKeywordInput() {
      debouncedKeywordSearch();
    }

    function onSortChange({ prop, order }) {
      if (!prop) {
        sortBy.value = "date";
        sortOrder.value = "desc";
      } else {
        sortBy.value = prop === "date" ? "date" : prop;
        sortOrder.value = order === "ascending" ? "asc" : "desc";
      }
      loadCommits();
    }

    function onPageChange(p) {
      page.value = p;
      loadCommits();
    }

    function onSelectionChange(rows) {
      const pageHashes = new Set(commits.value.map((c) => c.hash));
      const kept = selectedHashes.value.filter((h) => !pageHashes.has(h));
      const added = rows.map((r) => r.hash);
      selectedHashes.value = [...kept, ...added];
      refreshStats();
    }

    function tableRowClassName() {
      return "";
    }

    async function copyHash(hash) {
      const ok = await utils.copyText(hash);
      if (ok) {
        ElementPlus.ElMessage.success(`已复制 ${hash.slice(0, 7)}`);
      }
    }

    async function showDetail(row) {
      detailVisible.value = true;
      detailLoading.value = true;
      detail.value = null;
      try {
        detail.value = await api.getCommitDetail(row.hash);
      } catch (err) {
        ElementPlus.ElMessage.error(err.message);
        detailVisible.value = false;
      } finally {
        detailLoading.value = false;
      }
    }

    function typeTagType(t) {
      return utils.TYPE_COLORS[t] || "info";
    }

    function handleStreamEvent(ev) {
      if (ev.type === "log") {
        appendLog(ev.message, ev.level || "info");
      } else if (ev.type === "progress") {
        progress.value = ev.percent || 0;
        progressText.value = `${ev.current}/${ev.total} ${ev.hash ? ev.hash.slice(0, 7) : ""}`;
      } else if (ev.type === "backup") {
        lastBackup.branch = ev.backup_branch || "";
        lastBackup.restoreCommand = ev.restore_command || "";
        lastBackup.target = targetBranch.value;
        appendLog(`备份分支: ${lastBackup.branch}`, "info");
      } else if (ev.type === "conflict") {
        appendLog(ev.message || "冲突", "error");
        ElementPlus.ElNotification({
          title: "遇到冲突",
          message: ev.message || "整合已暂停",
          type: "warning",
          duration: 0,
        });
      } else if (ev.type === "report") {
        report.value = ev;
        if (ev.backup_branch) {
          lastBackup.branch = ev.backup_branch;
          lastBackup.restoreCommand = ev.restore_command || "";
          lastBackup.target = ev.target || targetBranch.value;
        }
      } else if (ev.type === "done") {
        loading.integrate = false;
        progress.value = ev.status === "completed" ? 100 : progress.value;
        if (ev.status === "completed") {
          ElementPlus.ElNotification({
            title: "整合完成",
            message: "提交已整合到目标分支",
            type: "success",
          });
          reportVisible.value = true;
        } else if (ev.status === "failed") {
          ElementPlus.ElNotification({
            title: "整合失败",
            message: "请查看日志了解详情",
            type: "error",
          });
          reportVisible.value = true;
        } else if (ev.status === "aborted") {
          ElementPlus.ElMessage.warning("整合已中止");
        }
        loadRepo().then(() => loadBranches());
      }
    }

    async function runPreview() {
      if (!selectedHashes.value.length) {
        ElementPlus.ElMessage.warning("请先选择提交");
        return;
      }
      await withError(async () => {
        previewResult.value = await api.previewConflicts({
          target: targetBranch.value,
          hashes: selectedHashes.value,
        });
        previewVisible.value = true;
        appendLog(
          `冲突预览: ${previewResult.value.conflict_count}/${previewResult.value.total} 可能冲突`,
          previewResult.value.conflict_count ? "warn" : "info"
        );
      }, "preview");
    }

    async function runIntegrate() {
      if (!selectedHashes.value.length) {
        ElementPlus.ElMessage.warning("请先选择提交");
        return;
      }
      if (!sourceBranch.value || !targetBranch.value) {
        ElementPlus.ElMessage.warning("请选择源分支与目标分支");
        return;
      }
      if (sourceBranch.value === targetBranch.value) {
        ElementPlus.ElMessage.warning("源分支与目标分支不能相同");
        return;
      }

      try {
        await ElementPlus.ElMessageBox.confirm(
          `将把 ${selectedHashes.value.length} 个提交从「${sourceBranch.value}」整合到「${targetBranch.value}」。\n` +
            `模式: ${integrateMode.value === "squash" ? "Squash" : "普通 cherry-pick"}\n` +
            `冲突策略: ${conflictStrategy.value}\n` +
            `整合前会自动创建备份分支。`,
          "确认整合",
          {
            type: "warning",
            confirmButtonText: "开始整合",
            cancelButtonText: "取消",
          }
        );
      } catch {
        return;
      }

      clearLogs();
      appendLog("开始整合…", "info");
      loading.integrate = true;
      progress.value = 0;

      try {
        const data = await api.startIntegrate({
          source: sourceBranch.value,
          target: targetBranch.value,
          hashes: selectedHashes.value,
          mode: integrateMode.value,
          conflict_strategy: conflictStrategy.value,
          squash_message: squashMessage.value,
        });
        currentJobId.value = data.job_id;
        if (eventSource.value) {
          eventSource.value.close();
        }
        eventSource.value = api.streamIntegrate(data.job_id, handleStreamEvent);
      } catch (err) {
        loading.integrate = false;
        ElementPlus.ElMessage.error(err.message);
        appendLog(err.message, "error");
      }
    }

    async function abortIntegrate() {
      if (!currentJobId.value) return;
      try {
        await api.abortIntegrate(currentJobId.value);
        appendLog("已请求中止", "warn");
      } catch (err) {
        ElementPlus.ElMessage.error(err.message);
      }
    }

    async function restoreLastBackup() {
      if (!lastBackup.branch || !lastBackup.target) {
        ElementPlus.ElMessage.warning("没有可恢复的备份");
        return;
      }
      try {
        await ElementPlus.ElMessageBox.confirm(
          `将目标分支「${lastBackup.target}」硬重置到备份「${lastBackup.branch}」。此操作不可轻易撤销，确认继续？`,
          "确认恢复",
          { type: "error", confirmButtonText: "恢复", cancelButtonText: "取消" }
        );
      } catch {
        return;
      }
      await withError(async () => {
        await api.restoreBackup({
          backup_branch: lastBackup.branch,
          target_branch: lastBackup.target,
        });
        ElementPlus.ElNotification({
          title: "已恢复",
          message: `已回滚到 ${lastBackup.branch}`,
          type: "success",
        });
        appendLog(`已恢复: ${lastBackup.restoreCommand}`, "info");
        await loadRepo();
        await loadBranches();
      }, "restore");
    }

    watch(sourceBranch, async (val, old) => {
      if (!val || val === old) return;
      filters.authors = [];
      selectedHashes.value = [];
      page.value = 1;
      await loadAuthors();
      await loadCommits();
    });

    onMounted(() => {
      loadRepo();
      appendLog("就绪。请确认仓库路径与分支后选择提交。", "info");
    });

    return {
      loading,
      repoPath,
      repoConfigured,
      currentBranch,
      repoClean,
      branches,
      sourceBranch,
      targetBranch,
      authors,
      filters,
      commits,
      total,
      page,
      pageSize,
      selectedHashes,
      selectedCount,
      stats,
      integrateMode,
      conflictStrategy,
      squashMessage,
      progress,
      progressText,
      logs,
      logBox,
      lastBackup,
      detailVisible,
      detailLoading,
      detail,
      helpVisible,
      previewVisible,
      previewResult,
      reportVisible,
      report,
      typeOptions,
      applyRepoPath,
      loadBranches,
      applyFilters,
      resetFilters,
      onKeywordInput,
      onSortChange,
      onPageChange,
      onSelectionChange,
      tableRowClassName,
      copyHash,
      showDetail,
      typeTagType,
      runPreview,
      runIntegrate,
      abortIntegrate,
      restoreLastBackup,
      clearLogs,
    };
  },
  template: `
  <div>
    <header class="app-header">
      <div class="brand">
        <div class="brand-title">Git 提交整合工具</div>
        <div class="brand-sub">可视化 cherry-pick / squash</div>
      </div>
      <div class="repo-bar">
        <el-input
          v-model="repoPath"
          placeholder="本地仓库绝对路径"
          clearable
          @keyup.enter="applyRepoPath"
        >
          <template #prepend>仓库</template>
        </el-input>
        <el-button type="primary" :loading="loading.repo" @click="applyRepoPath">应用</el-button>
      </div>
      <div class="header-meta">
        <el-tag v-if="currentBranch" type="success">当前: {{ currentBranch }}</el-tag>
        <el-tag v-if="repoConfigured" :type="repoClean ? 'info' : 'warning'">
          {{ repoClean ? '工作区干净' : '工作区有改动' }}
        </el-tag>
        <el-button text type="primary" @click="helpVisible = true">帮助</el-button>
      </div>
    </header>

    <div class="main" v-loading="loading.branches">
      <div class="left-col">
        <div class="panel">
          <div class="toolbar">
            <div class="field">
              <label>源分支</label>
              <el-select v-model="sourceBranch" filterable placeholder="选择源分支" style="width: 220px">
                <el-option v-for="b in branches" :key="'s-'+b" :label="b" :value="b" />
              </el-select>
            </div>
            <div class="field">
              <label>目标分支</label>
              <el-select v-model="targetBranch" filterable placeholder="选择目标分支" style="width: 220px">
                <el-option v-for="b in branches" :key="'t-'+b" :label="b" :value="b" />
              </el-select>
            </div>
          </div>

          <div class="filters">
            <div class="field" style="min-width: 220px">
              <label>作者</label>
              <el-select
                v-model="filters.authors"
                multiple
                collapse-tags
                collapse-tags-tooltip
                clearable
                filterable
                placeholder="全部作者"
                style="width: 240px"
                :loading="loading.authors"
              >
                <el-option
                  v-for="a in authors"
                  :key="a.name"
                  :label="a.name + ' (' + a.count + ')'"
                  :value="a.name"
                />
              </el-select>
            </div>
            <div class="field">
              <label>提交类型</label>
              <el-select
                v-model="filters.types"
                multiple
                collapse-tags
                clearable
                placeholder="全部类型"
                style="width: 200px"
              >
                <el-option v-for="t in typeOptions" :key="t" :label="t" :value="t" />
              </el-select>
            </div>
            <div class="field" style="min-width: 260px">
              <label>时间范围</label>
              <el-date-picker
                v-model="filters.dateRange"
                type="daterange"
                value-format="YYYY-MM-DD"
                start-placeholder="开始日期"
                end-placeholder="结束日期"
                style="width: 260px"
              />
            </div>
            <div class="field grow">
              <label>关键词</label>
              <el-input
                v-model="filters.keyword"
                clearable
                placeholder="按提交消息搜索"
                @input="onKeywordInput"
                @keyup.enter="applyFilters"
              />
            </div>
            <el-button type="primary" @click="applyFilters">筛选</el-button>
            <el-button @click="resetFilters">重置</el-button>
          </div>

          <div class="actions">
            <div class="field">
              <label>整合模式</label>
              <el-radio-group v-model="integrateMode">
                <el-radio-button label="normal">普通</el-radio-button>
                <el-radio-button label="squash">Squash</el-radio-button>
              </el-radio-group>
            </div>
            <div class="field" style="min-width: 280px">
              <label>冲突处理</label>
              <el-select v-model="conflictStrategy" style="width: 280px">
                <el-option value="pause" label="遇到冲突时暂停（手动解决）" />
                <el-option value="skip" label="自动跳过冲突提交" />
                <el-option value="ours" label="自动解决（使用 --ours）" />
              </el-select>
            </div>
            <div class="field grow" v-if="integrateMode === 'squash'">
              <label>Squash 提交说明</label>
              <el-input v-model="squashMessage" placeholder="可选，默认自动生成" />
            </div>
            <el-button :loading="loading.preview" @click="runPreview">预览冲突</el-button>
            <el-button
              type="primary"
              :loading="loading.integrate"
              :disabled="!selectedCount"
              @click="runIntegrate"
            >
              整合 ({{ selectedCount }})
            </el-button>
            <el-button
              type="danger"
              plain
              :disabled="!loading.integrate"
              @click="abortIntegrate"
            >
              中止
            </el-button>
          </div>

          <el-table
            v-loading="loading.commits"
            :data="commits"
            stripe
            border
            height="420"
            row-key="hash"
            @selection-change="onSelectionChange"
            @sort-change="onSortChange"
          >
            <el-table-column type="selection" width="48" reserve-selection />
            <el-table-column prop="index" label="序号" width="70" />
            <el-table-column label="哈希" width="110">
              <template #default="{ row }">
                <span class="hash-link" @click="copyHash(row.hash)" :title="'点击复制 ' + row.hash">
                  {{ row.short_hash }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="message" label="提交消息" min-width="220" sortable="custom" show-overflow-tooltip>
              <template #default="{ row }">
                <span :title="row.message">{{ row.message_short }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="author" label="作者" width="140" sortable="custom" />
            <el-table-column prop="date" label="日期" width="170" sortable="custom" />
            <el-table-column label="类型" width="100">
              <template #default="{ row }">
                <el-tag class="type-tag" size="small" :type="typeTagType(row.type)">{{ row.type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="showDetail(row)">详情</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px;">
            <span style="color:#6b7a90;font-size:13px;">
              已选 {{ selectedCount }} 条 · 共 {{ total }} 条
            </span>
            <el-pagination
              background
              layout="prev, pager, next, sizes"
              :total="total"
              v-model:current-page="page"
              v-model:page-size="pageSize"
              :page-sizes="[20, 50, 100]"
              @current-change="onPageChange"
              @size-change="() => { page = 1; applyFilters(); }"
            />
          </div>
        </div>
      </div>

      <aside class="stats-col">
        <div class="stat-card">
          <div class="label">源分支提交数</div>
          <div class="value">{{ stats.total_commits || total }}</div>
        </div>
        <div class="stat-card selected">
          <div class="label">已选提交</div>
          <div class="value">{{ selectedCount }}</div>
        </div>
        <div class="stat-card">
          <div class="label">涉及作者</div>
          <div class="value">{{ stats.author_count }}</div>
        </div>
        <div class="stat-card diff">
          <div class="label">代码变更</div>
          <div class="value">
            <span class="diff-plus">+{{ stats.additions }}</span>
            /
            <span class="diff-minus">-{{ stats.deletions }}</span>
          </div>
          <div class="sub">基于已选提交统计</div>
        </div>
      </aside>
    </div>

    <div class="panel footer-panel">
      <div class="log-header">
        <div class="log-title">操作日志</div>
        <div style="display:flex;gap:8px;align-items:center;flex:1;justify-content:flex-end;">
          <el-progress
            v-if="loading.integrate || progress > 0"
            :percentage="progress"
            :stroke-width="12"
            style="width: 220px"
          />
          <span v-if="progressText" style="font-size:12px;color:#6b7a90;">{{ progressText }}</span>
          <el-button size="small" @click="clearLogs">清空日志</el-button>
        </div>
      </div>
      <div class="log-box" ref="logBox">
        <div v-for="(line, i) in logs" :key="i" :class="['log-line', line.level]">
          [{{ line.time }}] {{ line.message }}
        </div>
      </div>
      <div class="backup-bar" v-if="lastBackup.branch">
        <span>最近备份:</span>
        <code>{{ lastBackup.branch }}</code>
        <span>恢复命令:</span>
        <code>{{ lastBackup.restoreCommand }}</code>
        <el-button
          size="small"
          type="warning"
          :loading="loading.restore"
          @click="restoreLastBackup"
        >
          一键恢复
        </el-button>
      </div>
    </div>

    <el-dialog v-model="detailVisible" title="提交详情" width="720px" destroy-on-close>
      <div v-loading="detailLoading">
        <template v-if="detail">
          <p><strong>哈希:</strong> <code>{{ detail.hash }}</code></p>
          <p><strong>作者:</strong> {{ detail.author }} &lt;{{ detail.email }}&gt;</p>
          <p><strong>日期:</strong> {{ detail.date }}</p>
          <p><strong>类型:</strong> {{ detail.type }}</p>
          <p><strong>变更:</strong>
            <span class="diff-plus">+{{ detail.additions }}</span> /
            <span class="diff-minus">-{{ detail.deletions }}</span>
          </p>
          <h4>消息</h4>
          <pre class="detail-pre">{{ detail.message }}</pre>
          <h4>文件统计</h4>
          <pre class="detail-pre">{{ detail.stat || '(无)' }}</pre>
        </template>
      </div>
    </el-dialog>

    <el-dialog v-model="previewVisible" title="冲突预览" width="640px">
      <template v-if="previewResult">
        <p>
          检测 {{ previewResult.total }} 个提交，
          可能冲突 <strong>{{ previewResult.conflict_count }}</strong> 个。
        </p>
        <el-table v-if="previewResult.conflicts.length" :data="previewResult.conflicts" size="small">
          <el-table-column prop="short_hash" label="哈希" width="100" />
          <el-table-column prop="message" label="消息" />
          <el-table-column prop="reason" label="原因" width="160" />
        </el-table>
        <el-empty v-else description="未检测到明显冲突" />
      </template>
    </el-dialog>

    <el-dialog v-model="reportVisible" title="整合结果报告" width="520px">
      <template v-if="report">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="状态">{{ report.status }}</el-descriptions-item>
          <el-descriptions-item label="成功">{{ report.success }}</el-descriptions-item>
          <el-descriptions-item label="跳过">{{ report.skipped }}</el-descriptions-item>
          <el-descriptions-item label="冲突">{{ report.conflicts }}</el-descriptions-item>
          <el-descriptions-item label="备份分支">{{ report.backup_branch || '-' }}</el-descriptions-item>
          <el-descriptions-item label="恢复命令">
            <code>{{ report.restore_command || '-' }}</code>
          </el-descriptions-item>
          <el-descriptions-item v-if="report.error" label="错误">{{ report.error }}</el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>

    <el-drawer v-model="helpVisible" title="使用帮助" size="420px">
      <div class="help-content">
        <h3>快速开始</h3>
        <ol>
          <li>设置本地 Git 仓库路径并点击「应用」</li>
          <li>选择源分支与目标分支</li>
          <li>按作者/类型/时间/关键词筛选提交</li>
          <li>勾选要整合的提交，点击「整合」</li>
        </ol>
        <h3>整合模式</h3>
        <p><strong>普通</strong>：逐个 cherry-pick，保留原提交历史。</p>
        <p><strong>Squash</strong>：将选中提交合并为一次新提交。</p>
        <h3>冲突策略</h3>
        <ul>
          <li><strong>暂停</strong>：遇到冲突停止，需手动处理或使用恢复。</li>
          <li><strong>跳过</strong>：自动跳过冲突提交继续。</li>
          <li><strong>--ours</strong>：保留目标分支版本（有风险）。</li>
        </ul>
        <h3>备份与恢复</h3>
        <p>整合前自动创建 <code>backup-目标分支-时间戳</code> 分支。可一键恢复或手动执行底部显示的命令。</p>
        <h3>启动方式</h3>
        <pre class="detail-pre">python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py --repo /path/to/repo
# 默认 http://127.0.0.1:5001 （勿用 5000，macOS AirPlay 会 403）</pre>
      </div>
    </el-drawer>
  </div>
  `,
};

const app = createApp(App);
app.use(ElementPlus);
app.mount("#app");
