import site
import os

for p in site.getsitepackages():
    f = os.path.join(p, 'pymilvus', 'client', '__init__.py')
    if os.path.exists(f):
        print('Found:', f)
        with open(f) as r:
            content = r.read()

        new_content = content.replace(
            'from pkg_resources import DistributionNotFound, get_distribution',
            'from importlib.metadata import PackageNotFoundError as DistributionNotFound\n'
            'def get_distribution(name):\n'
            '    from importlib.metadata import distribution\n'
            '    return distribution(name)'
        )

        with open(f, 'w') as w:
            w.write(new_content)

        print('Patched successfully.')
        break
    
    