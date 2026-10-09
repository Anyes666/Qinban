using System;
using System.Collections.Specialized;
using System.Configuration;
using System.IO;
using System.Xml.Linq;

namespace AutoMidiPlayer.Data.Properties;

/// <summary>
/// Custom settings provider that stores user settings in a fixed location
/// (%LocalAppData%\AutoMidiPlayer\user.config) instead of the versioned .NET default path.
/// This ensures settings persist across application updates.
/// </summary>
public class PortableSettingsProvider : SettingsProvider
{
    public static event EventHandler<Exception>? SaveFailed;

    private const string SettingsRootName = "configuration";
    private const string UserSettingsGroupName = "userSettings";

    private static string SettingsFilePath => AppPaths.UserConfigPath;

    public override string ApplicationName
    {
        get => "AutoMidiPlayer";
        set { }
    }

    public override string Name => "PortableSettingsProvider";

    public override void Initialize(string name, NameValueCollection config)
    {
        base.Initialize(Name, config);
    }

    public override SettingsPropertyValueCollection GetPropertyValues(
        SettingsContext context, SettingsPropertyCollection properties)
    {
        var values = new SettingsPropertyValueCollection();
        var settingsXml = LoadOrCreateSettings();

        foreach (SettingsProperty property in properties)
        {
            var value = new SettingsPropertyValue(property)
            {
                IsDirty = false
            };

            // Only handle user-scoped settings; application-scoped settings use defaults
            if (IsUserScopedSetting(property))
            {
                var savedValue = GetSettingValue(settingsXml, property.Name);
                if (savedValue != null)
                {
                    value.SerializedValue = savedValue;
                }
                else
                {
                    value.SerializedValue = property.DefaultValue;
                }
            }
            else
            {
                value.SerializedValue = property.DefaultValue;
            }

            values.Add(value);
        }

        return values;
    }

    public override void SetPropertyValues(
        SettingsContext context, SettingsPropertyValueCollection values)
    {
        var settingsXml = LoadOrCreateSettings();
        var settingsSection = GetOrCreateSettingsSection(settingsXml);

        foreach (SettingsPropertyValue value in values)
        {
            // Only save user-scoped settings
            if (!IsUserScopedSetting(value.Property))
                continue;

            var settingElement = settingsSection.Element(value.Name);
            if (settingElement == null)
            {
                settingElement = new XElement(value.Name);
                settingsSection.Add(settingElement);
            }

            settingElement.SetAttributeValue("serializeAs", "String");

            var valueElement = settingElement.Element("value");
            if (valueElement == null)
            {
                valueElement = new XElement("value");
                settingElement.Add(valueElement);
            }

            valueElement.Value = value.SerializedValue?.ToString() ?? string.Empty;
        }

        SaveSettings(settingsXml);
    }

    private static bool IsUserScopedSetting(SettingsProperty property)
    {
        return property.Attributes[typeof(UserScopedSettingAttribute)] is UserScopedSettingAttribute;
    }

    private static XDocument LoadOrCreateSettings()
    {
        if (File.Exists(SettingsFilePath))
        {
            try
            {
                return XDocument.Load(SettingsFilePath);
            }
            catch
            {
                // If file is corrupted, create new
            }
        }

        return new XDocument(
            new XElement(SettingsRootName,
                new XElement(UserSettingsGroupName)));
    }

    private static XElement GetOrCreateSettingsSection(XDocument doc)
    {
        var root = doc.Element(SettingsRootName);
        if (root == null)
        {
            root = new XElement(SettingsRootName);
            doc.Add(root);
        }

        var userSettings = root.Element(UserSettingsGroupName);
        if (userSettings == null)
        {
            userSettings = new XElement(UserSettingsGroupName);
            root.Add(userSettings);
        }

        return userSettings;
    }

    private static string? GetSettingValue(XDocument doc, string settingName)
    {
        var settingsSection = doc.Element(SettingsRootName)?.Element(UserSettingsGroupName);
        var settingElement = settingsSection?.Element(settingName);
        return settingElement?.Element("value")?.Value;
    }

    private static void SaveSettings(XDocument doc)
    {
        try
        {
            // Ensure directory exists
            AppPaths.EnsureDirectoryExists();
            doc.Save(SettingsFilePath);
        }
        catch (IOException ex)
        {
            // Ignore if disk is full or file is locked
            System.Diagnostics.Debug.WriteLine($"Failed to save settings: {ex.Message}");
            Logger.Log("Failed to save settings due to IOException.");
            Logger.LogException(ex);
            SaveFailed?.Invoke(null, ex);
        }
        catch (UnauthorizedAccessException ex)
        {
            // Ignore if permission denied
            System.Diagnostics.Debug.WriteLine($"Failed to save settings: {ex.Message}");
            Logger.Log("Failed to save settings due to UnauthorizedAccessException.");
            Logger.LogException(ex);
            SaveFailed?.Invoke(null, ex);
        }
    }
}
