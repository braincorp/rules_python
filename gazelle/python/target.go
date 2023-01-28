package python

import (
	"path/filepath"

	"github.com/bazelbuild/bazel-gazelle/config"
	"github.com/bazelbuild/bazel-gazelle/rule"
	"github.com/emirpasic/gods/sets/treeset"
	godsutils "github.com/emirpasic/gods/utils"
)

// targetBuilder builds targets to be generated by Gazelle.
type targetBuilder struct {
	kind              string
	name              string
	pythonProjectRoot string
	bzlPackage        string
	uuid              string
	srcs              *treeset.Set
	siblingSrcs       *treeset.Set
	deps              *treeset.Set
	resolvedDeps      *treeset.Set
	visibility        *treeset.Set
	main              *string
	imports           []string
	testonly          bool
}

// newTargetBuilder constructs a new targetBuilder.
func newTargetBuilder(kind, name, pythonProjectRoot, bzlPackage string, siblingSrcs *treeset.Set) *targetBuilder {
	return &targetBuilder{
		kind:              kind,
		name:              name,
		pythonProjectRoot: pythonProjectRoot,
		bzlPackage:        bzlPackage,
		srcs:              treeset.NewWith(godsutils.StringComparator),
		siblingSrcs:       siblingSrcs,
		deps:              treeset.NewWith(moduleComparator),
		resolvedDeps:      treeset.NewWith(godsutils.StringComparator),
		visibility:        treeset.NewWith(godsutils.StringComparator),
	}
}

// setUUID sets the given UUID for the target. It's used to index the generated
// target based on this value in addition to the other ways the targets can be
// imported. py_{binary,test} targets in the same Bazel package can add a
// virtual dependency to this UUID that gets resolved in the Resolver interface.
func (t *targetBuilder) setUUID(uuid string) *targetBuilder {
	t.uuid = uuid
	return t
}

// addSrc adds a single src to the target.
func (t *targetBuilder) addSrc(src string) *targetBuilder {
	t.srcs.Add(src)
	return t
}

// addSrcs copies all values from the provided srcs to the target.
func (t *targetBuilder) addSrcs(srcs *treeset.Set) *targetBuilder {
	it := srcs.Iterator()
	for it.Next() {
		t.srcs.Add(it.Value().(string))
	}
	return t
}

// addModuleDependency adds a single module dep to the target.
func (t *targetBuilder) addModuleDependency(dep module) *targetBuilder {
	if dep.Name+".py" == filepath.Base(dep.Filepath) || !t.siblingSrcs.Contains(dep.Name+".py") {
		t.deps.Add(dep)
	}
	return t
}

// addModuleDependencies copies all values from the provided deps to the target.
func (t *targetBuilder) addModuleDependencies(deps *treeset.Set) *targetBuilder {
	it := deps.Iterator()
	for it.Next() {
		t.addModuleDependency(it.Value().(module))
	}
	return t
}

// addResolvedDependency adds a single dependency the target that has already
// been resolved or generated. The Resolver step doesn't process it further.
func (t *targetBuilder) addResolvedDependency(dep string) *targetBuilder {
	t.resolvedDeps.Add(dep)
	return t
}

// addVisibility adds a visibility to the target.
func (t *targetBuilder) addVisibility(visibility string) *targetBuilder {
	t.visibility.Add(visibility)
	return t
}

// setMain sets the main file to the target.
func (t *targetBuilder) setMain(main string) *targetBuilder {
	t.main = &main
	return t
}

// setTestonly sets the testonly attribute to true.
func (t *targetBuilder) setTestonly() *targetBuilder {
	t.testonly = true
	return t
}

// generateImportsAttribute generates the imports attribute.
// These are a list of import directories to be added to the PYTHONPATH. In our
// case, the value we add is on Bazel sub-packages to be able to perform imports
// relative to the root project package.
func (t *targetBuilder) generateImportsAttribute() *targetBuilder {
	p, _ := filepath.Rel(t.bzlPackage, t.pythonProjectRoot)
	p = filepath.Clean(p)
	if p == "." {
		return t
	}
	t.imports = []string{p}
	return t
}

// build returns the assembled *rule.Rule for the target.
func (t *targetBuilder) build() *rule.Rule {
	r := rule.NewRule(t.kind, t.name)
	if t.uuid != "" {
		r.SetPrivateAttr(uuidKey, t.uuid)
	}
	if !t.srcs.Empty() {
		r.SetAttr("srcs", t.srcs.Values())
	}
	if !t.visibility.Empty() {
		r.SetAttr("visibility", t.visibility.Values())
	}
	if t.main != nil {
		r.SetAttr("main", *t.main)
	}
	if t.imports != nil {
		r.SetAttr("imports", t.imports)
	}
	if !t.deps.Empty() {
		r.SetPrivateAttr(config.GazelleImportsKey, t.deps)
	}
	if t.testonly {
		r.SetAttr("testonly", true)
	}
	r.SetPrivateAttr(resolvedDepsKey, t.resolvedDeps)
	return r
}
