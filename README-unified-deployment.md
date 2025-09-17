# Unified MPOS Deployment

This directory contains a unified Ansible deployment solution that handles both Linux and Windows servers in a single playbook.

## Files

- `unified-mpos-cd.yml` - Main deployment playbook for both Linux and Windows
- `unified-my-dynamic-inventory-mysql.yml` - Unified dynamic inventory configuration
- `configs.yml` - Configuration variables (referenced by playbook)

## Key Features

### Unified Approach
- Single playbook handles both Linux and Windows deployments
- Platform-specific tasks are conditionally executed based on `Srv_Type` variable
- Unified inventory includes both server types

### Platform Detection
The playbook automatically detects the server type using:
```yaml
is_linux: "{{ hostvars[inventory_hostname].Srv_Type == 'Linux' }}"
is_windows: "{{ hostvars[inventory_hostname].Srv_Type == 'Windows' }}"
```

### Dynamic Path Handling
- Linux: Uses `/tmp` as base path with `/` separators
- Windows: Uses `C:\temp` as base path with `\` separators
- Paths are dynamically constructed based on platform

### Service Management
- Linux: Uses `ansible.builtin.service` module
- Windows: Uses `ansible.windows.win_service` module
- Service names are configurable via `TMC_Tomcat_Service_Name` variable

## Usage

### Running the Unified Deployment

```bash
# Using the unified inventory
ansible-playbook -i unified-my-dynamic-inventory-mysql.yml unified-mpos-cd.yml

# Target specific server types
ansible-playbook -i unified-my-dynamic-inventory-mysql.yml unified-mpos-cd.yml --limit "Srv_Type:Linux"
ansible-playbook -i unified-my-dynamic-inventory-mysql.yml unified-mpos-cd.yml --limit "Srv_Type:Windows"

# Target specific clients
ansible-playbook -i unified-my-dynamic-inventory-mysql.yml unified-mpos-cd.yml --limit "Client_Name:YourClientName"
```

### Inventory Configuration

The unified inventory queries both Linux and Windows servers:
```sql
SELECT ... FROM view_mpos_update_info WHERE Srv_Type IN ('Linux', 'Windows');
```

## Migration from Separate Scripts

### Before (Separate Scripts)
- `linux-mpos-cd.yml` + `linux-my-dynamic-inventory-mysql.yml`
- `win-mpos-cd.yml` + `win-my-dynamic-inventory-mysql.yml`

### After (Unified)
- `unified-mpos-cd.yml` + `unified-my-dynamic-inventory-mysql.yml`

## Benefits

1. **Simplified Management**: Single playbook to maintain
2. **Consistent Logic**: Shared deployment logic with platform-specific adaptations
3. **Unified Monitoring**: Single point for deployment status and notifications
4. **Easier Maintenance**: Changes apply to both platforms automatically
5. **Reduced Duplication**: Eliminates code duplication between Linux and Windows scripts

## Platform-Specific Considerations

### Linux Tasks
- Uses `ansible.builtin.shell` for cleanup
- Uses `ansible.builtin.file` for directory creation
- Uses `ansible.builtin.service` for service management
- Uses `ansible.builtin.copy` with ownership/permissions

### Windows Tasks
- Uses `ansible.builtin.win_shell` for cleanup
- Uses `ansible.builtin.win_file` for directory creation
- Uses `ansible.windows.win_service` for service management
- Uses `ansible.builtin.win_copy` for file operations

## Error Handling

The playbook includes comprehensive error handling:
- Automatic rollback on deployment failure
- Database status updates for both success and failure cases
- Detailed email notifications with platform-specific information
- Backup file management and restoration

## Configuration

Ensure your `configs.yml` contains all necessary variables:
- `access_key` - AWS S3 access key
- `smtp_secure` - SMTP security setting (optional)
- Any other variables referenced in the playbook
