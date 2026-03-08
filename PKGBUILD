# Maintainer: PLACEHOLDER_NAME <PLACEHOLDER_EMAIL>
pkgname=ghastly
pkgver=0.1.0
pkgrel=1
pkgdesc="GitHub ActionS waTcher — terminal-native build monitor"
arch=('any')
url="https://github.com/PLACEHOLDER_OWNER/ghastly"
license=('GPL3')
depends=('python>=3.11' 'python-pip')
makedepends=('python-build' 'python-installer' 'python-wheel')
install="$pkgname.install"
source=("https://files.pythonhosted.org/packages/source/g/ghastly/ghastly-${pkgver}.tar.gz")
sha256sums=('PLACEHOLDER_SHA256')

build() {
    cd "$pkgname-$pkgver"
    python -m build --wheel --no-isolation
}

package() {
    cd "$pkgname-$pkgver"
    python -m installer --destdir="$pkgdir" dist/*.whl
}
