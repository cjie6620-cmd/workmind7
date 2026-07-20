<!-- frontend/src/views/KnowledgeView.vue -->
<!-- 知识库页：左侧上传 + 文档列表侧栏，右侧 RAG 问答区（纯组装，逻辑在子组件与 store） -->
<template>
  <div class="knowledge-view">
    <aside class="doc-panel">
      <DocumentUploader />
      <div class="divider" />
      <DocumentList />
    </aside>
    <RagChat />
  </div>
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useKnowledgeStore } from '@/stores/knowledge.js'
import DocumentUploader from '@/components/rag/DocumentUploader.vue'
import DocumentList from '@/components/rag/DocumentList.vue'
import RagChat from '@/components/rag/RagChat.vue'

const knStore = useKnowledgeStore()
onMounted(() => { knStore.loadDocuments(); knStore.loadCategories(); knStore.initSession() })
onUnmounted(() => { knStore.stopQuery(); knStore.stopUpload() })
</script>

<style scoped>
.knowledge-view { display:flex; height:100%; overflow:hidden; background:var(--color-bg); }
.doc-panel { width:300px; flex-shrink:0; background:var(--color-surface); border-right:1px solid var(--color-border); display:flex; flex-direction:column; overflow:hidden; }
.divider { height:1px; background:var(--color-border); flex-shrink:0; }
</style>
