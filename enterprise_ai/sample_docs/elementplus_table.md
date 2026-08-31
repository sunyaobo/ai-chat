# ElTable 表格组件使用说明（Element Plus 示例文档）

## 基本用法

`el-table` 用于展示多条结构类似的数据，可对数据进行排序、筛选、对比或其他自定义操作。

```vue
<template>
  <el-table :data="tableData" style="width: 100%">
    <el-table-column prop="date" label="日期" width="180" />
    <el-table-column prop="name" label="姓名" width="180" />
    <el-table-column prop="address" label="地址" />
  </el-table>
</template>

<script setup>
const tableData = [
  { date: '2024-05-01', name: '张三', address: '上海市普陀区金沙江路 1518 弄' },
  { date: '2024-05-02', name: '李四', address: '上海市普陀区金沙江路 1517 弄' },
]
</script>
```

## 自定义列内容

使用 `el-table-column` 的默认插槽可以完全自定义单元格内容：

```vue
<el-table :data="tableData">
  <el-table-column label="操作">
    <template #default="{ row }">
      <el-button size="small" @click="edit(row)">编辑</el-button>
      <el-button size="small" type="danger" @click="del(row)">删除</el-button>
    </template>
  </el-table-column>
</el-table>
```

插槽作用域暴露 `row`（当前行数据）、`column`、`$index`（行号）。

## 常用属性表

| 属性 | 说明 | 类型 | 默认值 |
|------|------|------|--------|
| data | 显示的数据 | array | — |
| stripe | 是否为斑马纹 | boolean | false |
| border | 是否有纵向边框 | boolean | false |
| height | 固定高度（表头固定） | string/number | — |
| loading | 加载动画 | boolean | false |
| row-key | 行 key（配合多选/展开/树形） | Function/String | — |
| selection | 多选需加 type="selection" 的列 | column type | — |

常用事件：`select`、`select-all`、`row-click`、`sort-change`。

## 排序与筛选

列上设置 `sortable` 开启排序；远程排序传 `sortable="custom"` 并监听 `sort-change`。筛选使用 `filters + filter-method`：

```vue
<el-table-column
  prop="tag"
  label="标签"
  :filters="[{ text: '家', value: '家' }, { text: '公司', value: '公司' }]"
  :filter-method="(value, row) => row.tag === value"
/>
```

## 常见坑位

1. 多选表格必须设置 `row-key`，否则翻页后选择状态丢失。
2. `height` 属性用于固定表头；动态高度可用 `max-height`。
3. 数据更新但视图未刷新时，检查是否使用了正确的响应式写法（ref/reactive）。
