from test_migrator import TestMigrator

if __name__ == '__main__':
    migrator = TestMigrator()
    migrator.perform_test_intentions('a11', 'b11', 'a12')
