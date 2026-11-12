## 改了什么

<!-- 一句话。读者靠这一句就能决定要不要往下看。 -->

## 为什么

<!-- 如果是修 bug：复现步骤与根因。如果是加东西：现在为什么做不到、这次为什么能做了。 -->

## 自查

- [ ] `python tools/check-links.py` 通过（改了文档就必须跑）
- [ ] `pwsh tools/pack.ps1` 通过（动了 `extension/` 就必须跑）
- [ ] 动了扩展行为，已 bump `extension/manifest.json` 的 `version`
- [ ] 动了端点 / 字段 / 错误码，已先改 `docs/contract.md`
- [ ] 一个提交只动一个目录族（`engine/` `extension/` `tools/` `docs/` 不混提）

## 实测记录（引擎改动必填）

<!--
CI 跑不了引擎：runner 上没有 229 MiB 模型，也没有 WASAPI。
所以引擎改动的证据只能是本机输出。贴命令和结果，不要写"本地测过"。
-->

```text
命令：
结果：
```
