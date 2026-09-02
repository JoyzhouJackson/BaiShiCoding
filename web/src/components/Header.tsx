const links = [
  ['foundation', '问题基础'],
  ['methods', '技术路线'],
  ['comparison', '结果对比'],
  ['simulation', '决策动画'],
  ['conclusion', '结论展望'],
]

export default function Header() {
  return (
    <>
      <header className="hero" id="top">
        <nav className="hero-nav" aria-label="顶部导航">
          <a className="brand" href="#top"><span>F</span> 快运优化实验室</a>
          <a className="source-link" href="./data/manifest.json" title="查看静态数据清单；原始数据路径记录在清单中">数据清单 ↗</a>
        </nav>
        <div className="hero-copy">
          <div className="hero-kicker">ROLLING DECISION · NETWORK OPTIMIZATION</div>
          <h1>动态快运网络班车开行与货物路由协同优化</h1>
          <p>面向需求预测偏差与随机异常的滚动决策方法比较</p>
          <div className="hero-badges">
            <span>12 例统一口径测试</span><span>3 种真实方法</span><span>36/36 结果验证通过</span><span>72 小时同步回放</span>
          </div>
        </div>
        <div className="hero-orbit" aria-hidden="true"><i /><i /><i /></div>
      </header>
      <nav className="section-nav" aria-label="章节导航">
        <a className="brand compact" href="#top"><span>F</span></a>
        <div>
          {links.map(([id, label]) => <a key={id} href={`#${id}`}>{label}</a>)}
        </div>
      </nav>
    </>
  )
}
