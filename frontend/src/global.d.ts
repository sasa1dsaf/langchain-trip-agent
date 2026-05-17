// 让 TypeScript 识别所有 CSS 文件
declare module '*.css' {
  const content: string;
  export default content;
}