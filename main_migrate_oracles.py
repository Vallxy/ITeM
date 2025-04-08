from test_migrator import TestMigrator

if __name__ == '__main__':
    migrator = TestMigrator()
    migrator.migration_test_oracles('a11', 'b11', 'a12', False)
