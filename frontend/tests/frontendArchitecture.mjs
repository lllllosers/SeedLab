import assert from 'node:assert/strict'
import path from 'node:path'
import ts from 'typescript'
import { parse } from '@vue/compiler-sfc'

export function scriptTree(source, file) {
  const descriptor = file.endsWith('.vue') ? parse(source).descriptor : undefined
  const script = descriptor ? [descriptor.script?.content, descriptor.scriptSetup?.content].filter(Boolean).join('\n') : source
  return ts.createSourceFile(file, script, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
}

export function dependencies(source, file) {
  const imports = []
  function visit(node) {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier)
      imports.push(node.moduleSpecifier.text)
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword
        && ts.isStringLiteral(node.arguments[0])) imports.push(node.arguments[0].text)
    ts.forEachChild(node, visit)
  }
  visit(scriptTree(source, file))
  return imports.filter(spec => spec.startsWith('.')).map(spec =>
    path.posix.normalize(path.posix.join(path.posix.dirname(file), spec)).replace(/\.(ts|vue)$/, ''))
}

export function assertFeatureDependencies(source, file) {
  for (const target of dependencies(source, file)) {
    const feature = target.match(/^features\/(experiments|germination|measurement)(?:\/|$)/)?.[1]
    const owner = file.match(/^features\/([^/]+)\//)?.[1]
    if (file.startsWith('shared/')) assert.equal(feature, undefined, 'shared imports a feature')
    if (feature && feature !== owner) {
      assert.ok(target === `features/${feature}` || target === `features/${feature}/index`,
        `private feature dependency: ${file} -> ${target}`)
      if (owner === 'experiments' && feature === 'germination')
        assert.equal(file, 'features/experiments/uiRegistry.ts', 'GER dispatch bypasses UI registry')
      if (owner === 'measurement')
        assert.equal(feature, 'experiments', 'measurement imports GER workflow')
    }
  }
}

export function assertNoLifecycleAuthority(source, file) {
  const forbidden = /^(can_?(complete|ready|start)|allowedTransitions|transitionRules|isTransitionAllowed)$/i
  function visit(node) {
    if (ts.isFunctionDeclaration(node) || ts.isVariableDeclaration(node)
        || ts.isMethodDeclaration(node) || ts.isPropertyAssignment(node))
      assert.ok(!forbidden.test(node.name?.getText() || ''), 'frontend lifecycle authority')
    ts.forEachChild(node, visit)
  }
  visit(scriptTree(source, file))
}
