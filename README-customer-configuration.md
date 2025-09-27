# Unified Customer Configuration for Jenkins Pipeline

This Jenkins pipeline has been updated to support multiple customers (CASA and Netsuite) with a unified configuration approach using conditional logic.

## Overview

The pipeline now uses a choice parameter to select the customer and reads configuration from unified files in the CIFile repository with conditional logic to handle customer-specific settings.

## Parameters

- **customer**: Choice parameter with options: `CASA`, `Netsuite`
- **release_tag**: SVN tag/branch name (e.g., trunk, v1.0, v2.1)
- **BasePath**: Base path where all required files are stored

## Configuration Files

### Required Files in CIFile Repository

You need to create the following files in your CIFile repository:

#### 1. Unified Checkout Configuration File

**`checkout-config.properties`**
```properties
# Unified Customer Configuration
# Format: localPath=svnPath
# %release_tag% will be replaced with the actual release tag
# %customer% will be replaced with the actual customer name

# Database Objects
DBObjects\sql=svn://repo.wondersoft.in/%customer%_web/CIFile/%release_tag%/SQL/%customer%_DB

# Jenkins Workspace
Workspace=svn://repo.wondersoft.in/%customer%_web/CIFile/%release_tag%/CICD/Jenkins/Workspace

# Source Code - Customer Specific
CASA\Source\Loyalty=svn://repo.wondersoft.in/eshopaid_web/CIFile/%release_tag%/FWL/LoyaltyVendors/CASA
CASA\Source\Runnables=svn://repo.wondersoft.in/eshopaid_web/CIFile/%release_tag%/IMWF/Lib/CustomizedRunnables/CASARunnables

Netsuite\Source\Integration=svn://repo.wondersoft.in/netsuite_web/CIFile/%release_tag%/Integration/Netsuite
Netsuite\Source\Runnables=svn://repo.wondersoft.in/netsuite_web/CIFile/%release_tag%/IMWF/Lib/CustomizedRunnables/NetsuiteRunnables

# Build Properties
build.properties=svn://repo.wondersoft.in/%customer%_web/CIFile/%release_tag%/build.properties

# Customer-specific boolean parameters
# CASA-specific parameters
Wondersoft_ShopaidExceptions=true
Wondersoft_Shopaid=true
Wondersoft=true
Wondersoft_ShopaidInterfaces=true
Newtonsoft_Json=true
Wondersoft_Logger=true
Wondersoft_Security_Cryptography=true
Wondersoft_IMWFLibrary=true
Wondersoft_Web_Help_dll=true
Wondersoft_Web_Help2=true
Wondersoft_IMWF_RunnableFactory=true

# Netsuite-specific parameters
Netsuite_Integration=true
Netsuite_WebServices=true
Netsuite_Logger=true
Netsuite_Security=true
Netsuite_IMWFLibrary=true
Netsuite_Web_Help_dll=true
Netsuite_Web_Help2=true
Netsuite_IMWF_RunnableFactory=true
```

#### 2. Unified Build Properties File

**`build.properties`**
```properties
# Unified Build Properties
# This file contains build-specific properties for all customers
# %customer% will be replaced with the actual customer name

# Version Information
VersionYear=2025
VersionMonth=01
VersionName=%customer%-v1.0

# Build Configuration
TargetFrameworkVersion=v4.5.2
ReferenceLibraries=${BasePath}\\ReferenceLibs\\lib
WorkspacePath=${BasePath}\\Workspace
TempDBPath=${BasePath}\\TempDBFiles

# Customer-specific paths
CASA_DBPath=${BasePath}\\DBObjects\\sql
CASA_DBSourcePath=${BasePath}\\DBObjects\\sql
CASA_IISPath=${BasePath}\\CASA\\Build\\IIS_eShopaid
CASA_HangfirePath=${BasePath}\\CASA\\Build\\IIS_Hangfire
CASA_SourceFolder=${BasePath}\\CASA\\Source
CASA_DBUpdatePath=${BasePath}\\CASA\\Build\\sql

Netsuite_DBPath=${BasePath}\\DBObjects\\sql
Netsuite_DBSourcePath=${BasePath}\\DBObjects\\sql
Netsuite_IISPath=${BasePath}\\Netsuite\\Build\\IIS_Netsuite
Netsuite_HangfirePath=${BasePath}\\Netsuite\\Build\\IIS_Hangfire
Netsuite_SourceFolder=${BasePath}\\Netsuite\\Source
Netsuite_DBUpdatePath=${BasePath}\\Netsuite\\Build\\sql

# CASA-specific build flags
Wondersoft_ShopaidExceptions=true
Wondersoft_Shopaid=true
Wondersoft=true
Wondersoft_ShopaidInterfaces=true
Newtonsoft_Json=true
Wondersoft_Logger=true
Wondersoft_Security_Cryptography=true
Wondersoft_IMWFLibrary=true
Wondersoft_Web_Help_dll=true
Wondersoft_Web_Help2=true
Wondersoft_IMWF_RunnableFactory=true

# Netsuite-specific build flags
Netsuite_Integration=true
Netsuite_WebServices=true
Netsuite_Logger=true
Netsuite_Security=true
Netsuite_IMWFLibrary=true
Netsuite_Web_Help_dll=true
Netsuite_Web_Help2=true
Netsuite_IMWF_RunnableFactory=true
```

## How It Works

1. **Customer Selection**: User selects customer (CASA or Netsuite) from the choice parameter
2. **Configuration Download**: Pipeline checks out the CIFile repository
3. **Unified Config Reading**: Pipeline reads `checkout-config.properties`
4. **Conditional Logic**: Pipeline executes only the relevant checkout commands based on customer selection
5. **Build Properties**: Pipeline loads `build.properties` and filters customer-specific properties
6. **Customer-Specific Build**: Build process uses customer-specific paths and settings
7. **S3 Upload**: Artifacts are uploaded to customer-specific S3 bucket paths

## Conditional Logic

### Checkout Stage
- **Customer-Specific Paths**: Lines starting with `CASA\` or `Netsuite\` are only executed for the respective customer
- **Placeholder Replacement**: `%customer%` and `%release_tag%` are replaced with actual values
- **Path Adjustment**: Customer-specific prefixes are removed from local paths

### Build Properties Stage
- **Customer-Specific Properties**: Properties starting with `CASA_` or `Netsuite_` are only included for the respective customer
- **Placeholder Replacement**: `%customer%` is replaced with actual customer name
- **Filtering**: Only relevant properties are loaded into the build environment

## S3 Bucket Structure

- **CASA**: `cicd-wspipeline/CASA/CASA-QC-Tags/{VersionYear}/{VersionMonth}/{VersionName}`
- **Netsuite**: `cicd-wspipeline/Netsuite/Netsuite-QC-Tags/{VersionYear}/{VersionMonth}/{VersionName}`

## Benefits

- **Single Configuration File**: All customer settings in one unified file
- **Easy Maintenance**: Add new customers by adding new sections to existing files
- **Flexible**: Each customer can have different SVN paths, build settings, and S3 locations
- **Scalable**: Easy to add more customers without changing the pipeline code
- **Conditional Logic**: Only relevant settings are processed for each customer

## Adding New Customers

To add a new customer (e.g., "NewCustomer"):

1. Add customer-specific sections to `checkout-config.properties`:
   ```properties
   NewCustomer\Source\Code=svn://repo.wondersoft.in/newcustomer_web/CIFile/%release_tag%/Source/NewCustomer
   ```

2. Add customer-specific sections to `build.properties`:
   ```properties
   NewCustomer_DBPath=${BasePath}\\DBObjects\\sql
   NewCustomer_SourceFolder=${BasePath}\\NewCustomer\\Source
   ```

3. Add "NewCustomer" to the choice parameter in Jenkinsfile

4. Update the conditional logic in the pipeline if needed

## Error Handling

- Pipeline fails immediately if configuration files are missing
- Clear error messages indicate which files are required
- No fallback to hardcoded values - ensures proper configuration
- Conditional logic prevents execution of irrelevant commands

## Example Execution

### For CASA Customer:
- Executes: `DBObjects\sql`, `Workspace`, `CASA\Source\Loyalty`, `CASA\Source\Runnables`
- Skips: `Netsuite\Source\Integration`, `Netsuite\Source\Runnables`
- Loads: All properties except those starting with `Netsuite_`

### For Netsuite Customer:
- Executes: `DBObjects\sql`, `Workspace`, `Netsuite\Source\Integration`, `Netsuite\Source\Runnables`
- Skips: `CASA\Source\Loyalty`, `CASA\Source\Runnables`
- Loads: All properties except those starting with `CASA_`